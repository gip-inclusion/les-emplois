from django.conf.urls import include, url

from .provider import PEAMUProvider
from .views import oauth2_callback as callback_view, oauth2_login as login_view


def default_urlpatterns(provider):
    urlpatterns = [
        url("^login/$", login_view, name=provider.id + "_login"),
        url("^login/callback/$", callback_view, name=provider.id + "_callback"),
    ]

    return [url("^" + provider.get_slug() + "/", include(urlpatterns))]


urlpatterns = default_urlpatterns(PEAMUProvider)
