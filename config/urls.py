from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path, register_converter
from django.views.generic import TemplateView

from itou.utils.urls import SiretConverter
from itou.www.dashboard import views as dashboard_views
from itou.www.login import views as login_views
from itou.www.signup import views as signup_views


register_converter(SiretConverter, "siret")

urlpatterns = [
    path("admin/", admin.site.urls),
    # --------------------------------------------------------------------------------------
    # allauth URLs. Order is important because some URLs are overriden.
    # --------------------------------------------------------------------------------------
    # Override allauth `account_signup` URL.
    # /accounts/signup/ <=> account_signup
    # We don't want any user to be able to signup using the default allauth `signup` url
    # because we have multiple specific signup processes for different kind of users.
    re_path(r"^accounts/signup/$", signup_views.signup),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_login` URL.
    # /accounts/login/ <=> account_login
    # We override this view because the login page should look slightly differently
    # for job seekers, prescribers and employers.
    # Also, PEAMU is only available for job seekers.
    re_path(r"^accounts/login/$", login_views.login),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_change_password` URL.
    # /accounts/password/change/ <=> account_change_password
    # https://github.com/pennersr/django-allauth/issues/468
    re_path(r"^accounts/password/change/$", dashboard_views.password_change),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_reset_password` URL.
    # Avoid user enumeration via password reset page.
    re_path(r"^accounts/password/reset/$", signup_views.ItouPasswordResetView.as_view()),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_logout` URL.
    # /accounts/logout/ <=> account_logout
    # We need custom code to process PEAMU logout.
    re_path(r"^accounts/logout/$", dashboard_views.logout),
    # --------------------------------------------------------------------------------------    # Other allauth URLs.
    path("accounts/", include("allauth.urls")),
    # --------------------------------------------------------------------------------------
    # PEAMU URLs.
    path("accounts/", include("itou.allauth_adapters.peamu.urls")),
    # --------------------------------------------------------------------------------------
    # API.
    path("api/v1/", include("itou.api.urls", namespace="v1")),
    # www.
    path("", include("itou.www.home.urls")),
    path("apply/", include("itou.www.apply.urls")),
    path("autocomplete/", include("itou.www.autocomplete.urls")),
    path("approvals/", include("itou.www.approvals_views.urls")),
    path("invitations/", include("itou.www.invitations_views.urls")),
    path("dashboard/", include("itou.www.dashboard.urls")),
    path("search/", include("itou.www.search.urls")),
    path("siae/", include("itou.www.siaes_views.urls")),
    path("prescribers/", include("itou.www.prescribers_views.urls")),
    path("releases/", include("itou.www.releases.urls")),
    path("signup/", include("itou.www.signup.urls")),
    path("stats/", include("itou.www.stats.urls")),
    path("welcoming_tour/", include("itou.www.welcoming_tour.urls")),
    path("employee_record/", include("itou.www.employee_record_views.urls")),
    # Errors pages.
    path("403/", TemplateView.as_view(template_name="403.html"), name="403"),
    path("404/", TemplateView.as_view(template_name="404.html"), name="404"),
    path("500/", TemplateView.as_view(template_name="500.html"), name="500"),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
