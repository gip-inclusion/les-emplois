from functools import wraps

from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views.decorators.debug import sensitive_post_parameters

from itou.openid_connect.france_connect.constants import FRANCE_CONNECT_SESSION_STATE, FRANCE_CONNECT_SESSION_TOKEN
from itou.openid_connect.pe_connect.constants import PE_CONNECT_SESSION_TOKEN
from itou.openid_connect.pro_connect.constants import PRO_CONNECT_SESSION_KEY


sensitive_post_parameters_password = method_decorator(
    sensitive_post_parameters("oldpassword", "password", "password1", "password2")
)


def check_user(test_func, err_msg=""):
    def decorator(view_func):
        def _check_user_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request.user)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(err_msg)

        return wraps(view_func)(_check_user_view_wrapper)

    return decorator


def get_logout_redirect_url(request):
    """
    Returns the URL to redirect to after the user logs out. Note that
    this method is also invoked if you attempt to log out while no user
    is logged in. Therefore, request.user is not guaranteed to be an
    authenticated user.
    Tests are in itou.inclusion_connect.tests.
    """
    redirect_url = reverse("search:employers_home")
    # ProConnect
    pro_session = request.session.get(PRO_CONNECT_SESSION_KEY)
    if pro_session:
        token = pro_session["token"]
        if token:
            params = {"token": token}
            pro_connect_base_logout_url = reverse("pro_connect:logout")
            return f"{pro_connect_base_logout_url}?{urlencode(params)}"
    # France Connect
    fc_token = request.session.get(FRANCE_CONNECT_SESSION_TOKEN)
    fc_state = request.session.get(FRANCE_CONNECT_SESSION_STATE)
    if fc_token:
        params = {"id_token": fc_token, "state": fc_state}
        fc_base_logout_url = reverse("france_connect:logout")
        return f"{fc_base_logout_url}?{urlencode(params)}"
    # PE Connect
    pe_token = request.session.get(PE_CONNECT_SESSION_TOKEN)
    if pe_token:
        params = {"id_token": pe_token}
        pe_base_logout_url = reverse("pe_connect:logout")
        return f"{pe_base_logout_url}?{urlencode(params)}"
    return redirect_url


class LoginNotRequiredMixin:
    @classmethod
    def as_view(cls, *args, **kwargs):
        view = super().as_view(*args, **kwargs)
        return login_not_required(view)
