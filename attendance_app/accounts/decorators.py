from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role != role:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


admin_required = role_required("admin")
faculty_required = role_required("faculty")
