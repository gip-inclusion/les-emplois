from functools import wraps

from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied


def check_user(test_func, err_msg=""):
    def decorator(view_func):
        def _check_user_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request.user)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(err_msg)

        return wraps(view_func)(_check_user_view_wrapper)

    return decorator


def check_request(test_func, err_msg=""):
    def decorator(view_func):
        def _check_request_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(err_msg)

        return wraps(view_func)(_check_request_view_wrapper)

    return decorator


class LoginNotRequiredMixin:
    @classmethod
    def as_view(cls, *args, **kwargs):
        view = super().as_view(*args, **kwargs)
        return login_not_required(view)
