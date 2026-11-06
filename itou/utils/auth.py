from functools import wraps

from allauth.account.auth_backends import AuthenticationBackend as BaseAuthenticationBackend
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.http import Http404


UserModel = get_user_model()


def check_user(test_func, err_msg=""):
    def decorator(view_func):
        def _check_user_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request.user)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(err_msg)

        return wraps(view_func)(_check_user_view_wrapper)

    return decorator


def check_user_or_404(test_func, err_msg=""):
    """Same as `check_user`, but hides the existence of the view instead of denying access."""

    def decorator(view_func):
        def _check_user_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request.user)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise Http404(err_msg)

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


class AuthenticationBackend(BaseAuthenticationBackend):
    def get_user(self, user_id):
        # The only addition is the use of `select_related` to avoid an
        # additional SQL query to build the user's full name
        # (displayed in the left column) when the user is a job
        # seeker.
        try:
            user = UserModel._default_manager.select_related("jobseeker_profile").get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
