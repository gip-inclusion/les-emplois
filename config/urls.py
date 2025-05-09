from anymail.webhooks.mailjet import MailjetTrackingWebhookView
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path, re_path, register_converter, reverse_lazy
from django.views.generic import RedirectView, TemplateView

from itou.utils import redirect_legacy_views
from itou.utils.urls import SiretConverter
from itou.www.dashboard import views as dashboard_views
from itou.www.error import server_error
from itou.www.login import views as login_views
from itou.www.signup import views as signup_views


register_converter(SiretConverter, "siret")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("hijack/", include("itou.utils.hijack.urls")),
    # --------------------------------------------------------------------------------------
    # allauth URLs. Order is important because some URLs are overriden.
    # --------------------------------------------------------------------------------------
    # Override allauth `account_signup` URL.
    # /accounts/signup/ <=> account_signup
    # We don't want any user to be able to signup using the default allauth `signup` url
    # because we have multiple specific signup processes for different kind of users.
    re_path(
        r"^accounts/signup/$", login_not_required(RedirectView.as_view(url=reverse_lazy("signup:choose_user_kind")))
    ),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_login` URL.
    # /accounts/login/ <=> account_login
    # Customized login pages per user type are handled by login.urls.
    re_path(r"^accounts/login/$", login_views.ItouLoginView.as_view()),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_change_password` URL.
    # /accounts/password/change/ <=> account_change_password
    # https://github.com/pennersr/django-allauth/issues/468
    re_path(r"^accounts/password/change/$", dashboard_views.ItouPasswordChangeView.as_view()),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_reset_password` URL.
    # Avoid user enumeration via password reset page.
    re_path(r"^accounts/password/reset/$", signup_views.ItouPasswordResetView.as_view()),
    # --------------------------------------------------------------------------------------
    # Override allauth `account_reset_password_from_key` URL.
    re_path(
        r"^accounts/password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
        signup_views.ItouPasswordResetFromKeyView.as_view(),
    ),
    # --------------------------------------------------------------------------------------
    # Other allauth URLs.
    path("accounts/", include("allauth.urls")),
    # --------------------------------------------------------------------------------------
    # PEAMU URLs.
    path("pe_connect/", include("itou.openid_connect.pe_connect.urls")),
    # FranceConnect URLs.
    path("franceconnect/", include("itou.openid_connect.france_connect.urls")),
    # ProConnect URLs.
    path("pro_connect/", include("itou.openid_connect.pro_connect.urls")),
    # --------------------------------------------------------------------------------------
    # API.
    path("api/v1/", include("itou.api.urls", namespace="v1")),
    path("api/", include("itou.www.api.urls")),
    # Status
    path("status/", include("itou.status.urls")),
    # www.
    path("", include("itou.www.home.urls")),
    path("apply/", include("itou.www.apply.urls")),
    path("approvals/", include("itou.www.approvals_views.urls")),
    path("autocomplete/", include("itou.www.autocomplete.urls")),
    path("dashboard/", include("itou.www.dashboard.urls")),
    path("eligibility/", include("itou.www.eligibility_views.urls")),
    path("employee_record/", include("itou.www.employee_record_views.urls")),
    path("employees/", include("itou.www.employees_views.urls")),
    path("geiq-assessments/", include("itou.www.geiq_assessments_views.urls")),
    path("institutions/", include("itou.www.institutions_views.urls")),
    path("invitations/", include("itou.www.invitations_views.urls")),
    path("job-seekers/", include("itou.www.job_seekers_views.urls")),
    path("prescribers/", include("itou.www.prescribers_views.urls")),
    path("search/", include("itou.www.search.urls")),
    path("company/", include("itou.www.companies_views.urls")),
    re_path(r"^siae/.*$", redirect_legacy_views.redirect_siaes_views),
    path("siae_evaluation/", include("itou.www.siae_evaluations_views.urls")),
    path("login/", include("itou.www.login.urls")),
    path("logout/", include("itou.www.logout.urls")),
    path("signup/", include("itou.www.signup.urls")),
    path("stats/", include("itou.www.stats.urls")),
    path("announcements/", include("itou.www.announcements.urls")),
    path("versions/", include("itou.www.releases.urls")),
    # Enable Mailjet status tracking
    # https://anymail.readthedocs.io/en/stable/esps/mailjet/#status-tracking-webhooks
    path("webhooks/anymail/mailjet/tracking/", login_not_required(MailjetTrackingWebhookView.as_view())),
    path("welcoming_tour/", include("itou.www.welcoming_tour.urls")),
    # Static pages.
    path(
        "accessibility/",
        login_not_required(TemplateView.as_view(template_name="static/accessibility.html")),
        name="accessibility",
    ),
    path(
        "legal/notice/",
        login_not_required(TemplateView.as_view(template_name="static/legal/notice.html")),
        name="legal-notice",
    ),
    path(
        "legal/privacy/",
        login_not_required(TemplateView.as_view(template_name="static/legal/privacy.html")),
        name="legal-privacy",
    ),
    path(
        "legal/terms/",
        login_not_required(TemplateView.as_view(template_name="static/legal/terms.html")),
        name="legal-terms",
    ),
    path("", include("itou.www.security.urls")),
    path("gps/", include("itou.www.gps.urls")),
    path("rdvi/", include("itou.www.rdv_insertion.urls")),
    path("staff/", include("itou.www.itou_staff_views.urls")),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns


handler500 = server_error
