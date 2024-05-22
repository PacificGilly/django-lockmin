from collections import namedtuple
from logging import getLogger
from typing import Any, ClassVar, Optional, Type, override

from django.contrib import messages
from django.contrib.admin import ModelAdmin, action, display
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Model, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from django_lockmin.typing import PermissionType


log = getLogger(__name__)


class AdminLockingMixin(ModelAdmin):
    """
    Provides functionality to "lock" a record from being accessed or changed.

    :warning: This requires you to create a foreign key with the User table to the model you want
    to restrict access against. :warning:

    :param allow_view_permissions:
        Whether the user can still view the record even if it's locked by another user. If it's
        locked, then they're not allowed to make any changes to the record.
    :param model_reference_key:
        Used to identify the field on the model that provides a human-readable identifier. The
        primary key is not always the most human-readable, but will be used by default.
    :param max_records_lockable:
        Specify how many records that a specific user is allowed to lock at any given time.
    :param max_records_warning_msg:
        Specify the warning message displayed to the user if they try to lock more than the
        `max_records_lockable` amount of records.
    :param locked_error_msg:
        Specify the error message displayed to the user if they try to access an already locked
        record that's not assigned to themselves. This works regardless of the setting of
        `allow_view_permissions`.
    :param user_field:
        The name of the model field you are building a locking mechanism for that has a foreign
        key to the User table.
    :param locking_help:
        Specify the inf message displayed to the user when the open up the dashboard after
        logging in. This could provide details about how the locking mechanism works, for example.
    :param lock_record_action_name:
        Specify the display name of the lock action.
    :param unlock_record_action_name:
        Specify the display name of the unlock action.
    :param unlock_record_action_permission:
        Specify any special permissions that are needed to unlock a record. These permissions
        will be created automatically for you by default. If you prefer a different name for the
        unlocking permission then set this here. If you don't want special controls, then set
        this as None which will give every user access to this admin view unlocking controls.

    :example:
        As `AdminLockingMixin` already inherits from ModelAdmin we don't need to inherit from
        multiple parents.
        ```
        class MyModel(models.Model):
            ...
            user = models.ForeignKey(User, on_delete=models.CASCADE)


        @register(MyModel)
        class MyAdminModelView(AdminLockingMixin):
            ...
        ```
    """

    allow_view_permissions: bool = False
    model_reference_key: str = "pk"
    max_records_lockable: int = 1
    max_records_warning_msg: str = (
        f"You can only lock upto {max_records_lockable} record(s)"
    )
    locked_error_msg: str = "This record is locked. Please try again later."
    user_field: str = "user"
    locking_help: Optional[str] = None
    lock_record_action_name: str = "Lock Record"
    unlock_record_action_name: str = "Unlock Record"
    unlock_record_action_permission: Optional[PermissionType] = PermissionType(
        codename="unlock", description="Can unlock a record."
    )

    # Force users to use the actions to lock the record.
    list_display_links = None

    # Class variables to define the actions and extra columns to bolt on to the admin view.
    LOCKED_BY_COLUMN: ClassVar[str] = "is_locked_by"
    UNLOCK_RECORD: ClassVar[str] = "unlock_record"
    LOCK_RECORD: ClassVar[str] = "lock_record"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Adds additional components to the admin view specifically about the locking mechanism.

        - Appends the "is_locked" column to the admins `list_display`.
        - Adds two actions; one for locking the record, and another for unlocking the record.

        This shouldn't be initialised explicitly, but rather let Django themselves initialise this
        when the ModelAdmin is initialised.
        """
        super().__init__(*args, **kwargs)

        # Dynamically register the `is_locked_by` list column.
        if not self.list_display:
            self.list_display = (self.LOCKED_BY_COLUMN,)
        elif self.LOCKED_BY_COLUMN not in self.list_display:
            self.list_display += (self.LOCKED_BY_COLUMN,)  # type: ignore[operator]

        # Dynamically register the action to unlock a record.
        if not self.actions:
            self.actions = (self.UNLOCK_RECORD,)
        elif self.UNLOCK_RECORD not in self.actions:
            self.actions += (self.UNLOCK_RECORD,)  # type: ignore[operator]
        AdminLockingMixin.unlock_record.short_description = (  # type: ignore[attr-defined]
            self.unlock_record_action_name
        )

        # Dynamically register the action to lock a record.
        if not self.actions:
            self.actions = (self.LOCK_RECORD,)
        elif self.LOCK_RECORD not in self.actions:
            self.actions += (self.LOCK_RECORD,)  # type: ignore[operator]
        AdminLockingMixin.lock_record.short_description = (  # type: ignore[attr-defined]
            self.lock_record_action_name
        )

        self._validate_user_field()

    def _get_changeview_url(self, obj: models.Model) -> str:
        """
        Gets the URL of the change view for a specific model record.
        """
        return reverse(
            f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
            args=[obj.pk],
        )

    def _set_unlock_permission(self) -> None:
        """
        Sets the user permission for unlocking a record and attaches the relevant method to check a
        user has the permission.
        """
        if not self.unlock_record_action_permission:
            return

        full_codename = get_permission_codename(
            self.unlock_record_action_permission.codename, self.opts
        )

        # If not already defined, create the "unlock" permission.
        if not Permission.objects.filter(codename=full_codename).count():
            content_type = ContentType.objects.get_for_model(self.model)
            Permission.objects.create(
                codename=full_codename,
                name=self.unlock_record_action_permission.description,
                content_type=content_type,
            )

        # Link this newly created permission to the specific action method, `unlock_record`.
        AdminLockingMixin.unlock_record.allowed_permissions = [  # type: ignore[attr-defined]
            self.unlock_record_action_permission.codename
        ]

    def _validate_user_field(self) -> None:
        """
        Ensure that the model attached to the admin view has a correct user attribute so we can
        track which user has locked a record.
        """
        if not hasattr(self.model, self.user_field):
            raise ValueError(
                f"The `user_field` was set to `{self.user_field}` but that's not a model field of "
                f"`{self.model.__name__}`"
            )
        elif getattr(self.model, self.user_field).field.related_model != User:
            raise ValueError(
                f"The `user_field` was set to `{self.user_field}` but that isn't a foreign key to "
                f"the User table."
            )
        return None

    def is_locked(self, request: HttpRequest, obj: models.Model) -> bool:
        user: User = getattr(obj, self.user_field)
        assert request.user, "User must be logged in!"
        return user.id != request.user.id

    @action
    def unlock_record(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Provides an action ability to unlock a record.

        Access should be limited to higher-level users.
        """
        for manual_order_attempt in queryset:
            manual_order_attempt.user = None
            manual_order_attempt.save(update_fields=["user"])
        model_references = queryset.values_list(self.model_reference_key, flat=True)
        model_references_str = ", ".join(model_references)

        self.message_user(
            request,
            f"Successfully unlocked the following records: {model_references_str}",
            level=messages.SUCCESS,
        )

        return None

    @action
    def lock_record(
        self, request: HttpRequest, queryset: QuerySet
    ) -> Optional[HttpResponseRedirect]:
        """
        Provides an action ability to lock a record.

        Using an action to lock a record rather than allowing a user to click on the dashboard
        elements to make it very explicit the action the user is taking.
        """
        # Joins both the queryset that we want to process as well at the query set of records we
        # have already locked, incase a user tries to lock the same record they've already locked.
        all_records_for_user = queryset.union(
            self.model.objects.filter(**{self.user_field: request.user.pk})
        )

        # Check that we're not requesting to access more records than we're allowed at any one time.
        if all_records_for_user.count() > self.max_records_lockable:
            self.message_user(
                request, message=self.max_records_warning_msg, level=messages.ERROR
            )
            # Optionally allow user to keep viewing a record (commented out).
            # return None

        record = queryset.get()
        return redirect(self._get_changeview_url(record))

    @display(description=_("Locked By"), ordering="-user__last_name")
    def is_locked_by(self, obj: Type[Model]) -> str:
        """
        Display the user who has locked the record.
        """
        user: Optional[User] = getattr(obj, self.user_field)
        if not user:
            return "-"

        if not user.first_name and not user.last_name:
            log.warning(
                f"The user `{user.username}` has no first or last name set. Please set their user "
                f"details for improved visibility of who's locked a manual order."
            )
            return user.username

        return f"{user.first_name} {user.last_name}"

    @override
    def has_view_permission(
        self, request: HttpRequest, obj: Optional[models.Model] = None
    ) -> bool:
        """
        Grant view permissions as this is always required regardless of whether
        `allow_view_permissions` is true or false, as we want to override any other mixins that
        might have set this to False. Otherwise, if the user is allowed to view the locked record,
        you'll get a 403 back from Django.
        """
        return True

    @override
    def has_change_permission(
        self, request: HttpRequest, obj: Optional[models.Model] = None
    ) -> bool:
        """
        Prevent the user from being able to change the data in an admin view if the record is
        already locked.
        """
        if not obj:
            return True
        return not self.is_locked(request, obj=obj)

    def has_unlock_permission(self, request: HttpRequest) -> bool:
        """
        Checks to see if the user have the `unlock` permission for the specific model.

        Links to the `unlock_order` method to set the `unlock` permission.
        """
        if not self.unlock_record_action_permission:
            return True

        codename = get_permission_codename(
            self.unlock_record_action_permission.codename, self.opts
        )

        # Avoids having to reload the application and get the latest permissions for the user [0]
        # [0] https://docs.djangoproject.com/en/5.0/topics/auth/default/#permission-caching
        user: User = get_object_or_404(User, pk=request.user.id)
        return user.has_perm("%s.%s" % (self.opts.app_label, codename))

    @override
    def get_model_perms(self, request: HttpRequest) -> dict[str, bool]:
        """
        Adds the permission to "unlock" a locked record.

        This will get called not at the point of running the app, but when the admin page is loaded.
        """
        perms = super().get_model_perms(request)

        # If the permission has been nullified, then lets give everyone access.
        if not self.unlock_record_action_permission:
            return perms

        # Initialise the unlock permission.
        self._set_unlock_permission()

        # Append the new "unlock" permission to the set.
        perms[self.unlock_record_action_permission.codename] = (
            self.has_unlock_permission(request)
        )

        return perms

    @override
    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: Optional[dict[str, Any]] = None,
    ) -> TemplateResponse | HttpResponseRedirect | HttpResponse:
        """
        Checks to see if an existing record is already being processed by another user and blocks
        any other user from changing the record (and optionally even viewing the record).
        """
        model = self.model.objects.get(id=object_id)
        user: User = getattr(model, self.user_field)

        if not user:
            setattr(model, self.user_field, request.user)
            model.save(update_fields=[self.user_field])
            return super().change_view(request, object_id)

        elif self.is_locked(request, model):
            self.message_user(
                request, message=self.locked_error_msg, level=messages.ERROR
            )

            # Redirect back to the list view if view access is not allowed. The error message
            # will be displayed on either the index view or the details view regardless.
            if not self.allow_view_permissions:
                return HttpResponseRedirect("../../")

        return super().change_view(request, object_id)

    @override
    def changelist_view(
        self, request: HttpRequest, extra_context: Optional[dict[str, Any]] = None
    ) -> HttpResponse:
        """
        Display an optional welcome message for users to the locked dashboard.
        """

        # Give users a helpful one-time only welcome message when they first access the admin
        # view after logging in.
        if self.locking_help and not request.session.get("message_seen", False):
            self.message_user(request, self.locking_help, level=messages.INFO)
            request.session["message_seen"] = True
        return super().changelist_view(request, extra_context=extra_context)
