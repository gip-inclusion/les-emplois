from anymail.webhooks.mailjet import MailjetTrackingWebhookView
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path, re_path, register_converter
from django.views.generic import TemplateView

from itou.utils import redirect_legacy_views
from itou.utils.urls import SiretConverter
from itou.www.error import server_error


register_converter(SiretConverter, "siret")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("hijack/", include("itou.utils.hijack.urls")),
    # --------------------------------------------------------------------------------------
    # PEAMU URLs.
    path("pe_connect/", include("itou.openid_connect.pe_connect.urls")),
    # FranceConnect URLs.
    path("franceconnect/", include("itou.openid_connect.france_connect.urls")),
    # Inclusion Connect URLs.
    path("inclusion_connect/", include("itou.openid_connect.inclusion_connect.urls")),
    # ProConnect URLs.
    path("pro_connect/", include("itou.openid_connect.pro_connect.urls")),
    # Authentication and account management URLs.
    path("accounts/", include("itou.www.accounts.urls")),
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
    path("employee_record/", include("itou.www.employee_record_views.urls")),
    path("employees/", include("itou.www.employees_views.urls")),
    path("geiq/", include("itou.www.geiq_views.urls")),
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
