from django.contrib.auth.decorators import login_not_required
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework import routers

from itou.api.applicants_api.views import ApplicantsView
from itou.api.c4_api.views import C4CompanyView
from itou.api.data_inclusion_api.views import DataInclusionStructureView
from itou.api.employee_record_api.viewsets import EmployeeRecordUpdateNotificationViewSet, EmployeeRecordViewSet
from itou.api.geiq.views import GeiqJobApplicationListView
from itou.api.job_application_api.views import JobApplicationSearchView
from itou.api.redoc_views import ItouSpectacularRedocView
from itou.api.siae_api.viewsets import SiaeViewSet
from itou.api.token_auth.views import ObtainAuthToken


# High level app for API
# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "itou.api"

# Using DRF router with viewsets means automatic definition of URL patterns
router = routers.DefaultRouter()
router.register(r"employee-records", EmployeeRecordViewSet, basename="employee-records")
router.register(
    r"employee-record-notifications",
    EmployeeRecordUpdateNotificationViewSet,
    basename="employee-record-notifications",
)
router.register(r"siaes", SiaeViewSet, basename="siaes")

urlpatterns = [
    # TokenAuthentication endpoint to get token from login/password.
    path("token-auth/", ObtainAuthToken.as_view(), name="token-auth"),
    # Needed for Browsable API (dev)
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    path("embauches-geiq/", GeiqJobApplicationListView.as_view(), name="geiq_jobapplication_list"),
    # OpenAPI
    # See: https://www.django-rest-framework.org/topics/documenting-your-api/
    # OAS 3 YAML schema (downloadable)
    path(
        "oas3/",
        login_not_required(SpectacularAPIView.as_view()),
        name="openapi_schema",
    ),
    path(
        "redoc/",
        ItouSpectacularRedocView.as_view(url_name="v1:openapi_schema"),
        name="redoc",
    ),
]

urlpatterns += router.urls

urlpatterns += [
    path("structures/", DataInclusionStructureView.as_view(), name="structures-list"),
    path("candidats/", ApplicantsView.as_view(), name="applicants-list"),
    path("candidatures/recherche/", JobApplicationSearchView.as_view(), name="job-applications-search"),
    path("marche/", C4CompanyView.as_view(), name="marche-company-list"),
]
