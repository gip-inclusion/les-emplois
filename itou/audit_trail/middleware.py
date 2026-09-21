import datetime
import secrets

from django.conf import settings


def browser_id_cookie(get_response):
    """Set a cookie to browsers interacting with the website.

    This allows to track a browser from a session to another in the audit trail.

    POSTing triggers the initial creation of a cookie, not
    authentication: we want to have a value for this cookie **before**
    the user authentication so the event can be tracked.

    See docs/audit_trail.md for more information.
    """

    def middleware(request):
        """Cookies contain 16 random bytes, so 128 bits (like a UUID)."""
        request.browser_id = request.COOKIES.get(settings.BROWSER_ID_COOKIE_NAME)
        if request.method == "POST" and not request.browser_id:
            request.browser_id = secrets.token_urlsafe(16)

        response = get_response(request)

        if request.method == "POST" and request.browser_id:
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
