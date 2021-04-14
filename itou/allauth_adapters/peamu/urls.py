from django.urls import include, path

from itou.allauth_adapters.peamu.provider import PEAMUProvider
from itou.allauth_adapters.peamu.views import oauth2_callback as callback_view, oauth2_login as login_view


def default_urlpatterns(provider):
    urlpatterns = [
        path("login", login_view, name=provider.id + "_login"),
        path("login/callback", callback_view, name=provider.id + "_callback"),
    ]

    return [path(provider.get_slug(), include(urlpatterns))]


urlpatterns = default_urlpatterns(PEAMUProvider)
