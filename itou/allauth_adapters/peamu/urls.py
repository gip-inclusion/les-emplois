from django.urls import include, re_path

from itou.allauth_adapters.peamu import views as peamu_views
from itou.allauth_adapters.peamu.provider import PEAMUProvider


def default_urlpatterns(provider):
    urlpatterns = [
        re_path(r"^login/$", peamu_views.oauth2_login, name=provider.id + "_login"),
        re_path(r"^login/callback/$", peamu_views.oauth2_callback, name=provider.id + "_callback"),
    ]

    return [
        re_path(r"^profile/$", peamu_views.redirect_to_dashboard_view),
        re_path(r"^" + provider.get_slug() + r"/", include(urlpatterns)),
    ]


urlpatterns = default_urlpatterns(PEAMUProvider)
