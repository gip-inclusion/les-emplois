import datetime
import secrets

from django.conf import settings
from django.urls import reverse


WRITING_GETS = {  # Known GET requests that modify server state
    reverse("france_connect:callback"),
    reverse("ft_connect:callback"),
    reverse("pro_connect:callback"),
}


def _should_set_cookie(request):
    """Tell if this request is interesting enough to initiate browser tracking.

    To avoid useless calls to secrets.token_urlsafe(), and to avoid
    tracking users and bots that do not modify the server state we
    don’t create the cookie on every request.

    We're only creating the cookie for requests that modify the server
    state.
    """
    return request.method == "POST" or request.path in WRITING_GETS


def browser_id_cookie(get_response):
    """Set a cookie to browsers interacting with the website.

    This allows to track a browser from a session to another in the audit trail.

    It is a middleware to have a value for this cookie **before** the
    user authentication so the log-in event can be tracked.

    See docs/audit_trail.md for more information.
    """

    def middleware(request):
        """Cookies contain 16 random bytes, so 128 bits (like a UUID)."""
        request.browser_id = request.COOKIES.get(settings.BROWSER_ID_COOKIE_NAME)
        if _should_set_cookie(request) and not request.browser_id:
            request.browser_id = secrets.token_urlsafe(16)

        response = get_response(request)

        if _should_set_cookie(request) and request.browser_id:
            # Renew the cookie (push its expiration).
            response.set_cookie(
                settings.BROWSER_ID_COOKIE_NAME,
                request.browser_id,
                max_age=datetime.timedelta(days=45),
                httponly=True,
                samesite="Strict",
            )

        return response

    return middleware
