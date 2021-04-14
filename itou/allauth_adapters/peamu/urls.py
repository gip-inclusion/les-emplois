from django.urls import include, re_path

from itou.allauth_adapters.peamu.provider import PEAMUProvider
from itou.allauth_adapters.peamu.views import oauth2_callback as callback_view, oauth2_login as login_view


def default_urlpatterns(provider):
    urlpatterns = [
        re_path(r"^login/$", login_view, name=provider.id + "_login"),
        re_path(r"^login/callback/$", callback_view, name=provider.id + "_callback"),
    ]

    return [re_path(r"^" + provider.get_slug() + r"/", include(urlpatterns))]


urlpatterns = default_urlpatterns(PEAMUProvider)
