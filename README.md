Django-Lockmin
-----------------------------

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) 
    ![PyPI download month](https://img.shields.io/pypi/dm/django-lockmin.svg)
    [![PyPI version](https://badge.fury.io/py/django-jazzmin.svg)](https://pypi.python.org/pypi/django-lockmin/)
    ![Python versions](https://img.shields.io/badge/python-%3E=3.12-brightgreen)
    ![Django Versions](https://img.shields.io/badge/django-%3E=4.2-brightgreen)
    [![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff) 

A drop-in mixin to add the ability to lock down specific Django admin views to only allow a single user to make updates to a record.

### Features
- Single user assigned to a record of a model
- Restricts access to other users attempting to access the record (via the admin interface only).
- The level of restriction can be adjusted - allows giving view-only access or completely blocks access
- Control how many records a specific users can access (See use cases for different examples)
- Explicit locking controls using the admin actions (To avoid users accidently assigning a record to themselves)
- Ability to unlock records, with additional user restrictions.
- Control over the messages displayed to users from how to use the locking mechanism to why they can't access a record (because its locked).

### Pre-requisites
- Requires the model you're creating an admin view for has a foreign key to the user table so this mixin can assign a specific authenticated user to the record they've accessed.

### Example use cases
- Processing manual orders which are only allowed by a single operator
- Assign a user to a record who is now responsible for that record (e.g. incident reporting, customer query).

### Installation
Using pip:
```bash
pip install django-lockmin
```
Or using Poetry:
```bash
poetry add django-lockmin
```

### Usage
Since this is a pure mixin, you don't need to add this project to a list of installed apps (although you can if you like the visibility).
```python
INSTALLED_APPS = [
    ...,
    "lockmin",
    ...
]
```

All you need to do is simply inherit soley from the `AdminLockableMixin`
```python
from django.contrib.admin import register
from django.contrib.auth.models import User
from django.db import models
from django_lockmin import AdminLockableMixin


class MyModel(models.Model):
    ...
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    
@register(MyModel)
class MyAdminView(AdminLockableMixin):
    ...
```
To see all the options you can set in your admin view, check the [docstring in AdminLockableMixin](src/django_lockmin/admin.py)