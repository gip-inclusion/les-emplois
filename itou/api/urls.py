from django.contrib.auth.decorators import login_not_required
from django.urls import path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView
from rest_framework import routers

from itou.api.applicants_api.views import ApplicantsView
from itou.api.data_inclusion_api.views import DataInclusionStructureView
from itou.api.employee_record_api.viewsets import EmployeeRecordViewSet
from itou.api.geiq.views import GeiqJobApplicationListView
from itou.api.inbound_parsing.views import BrevoInboundParsingView
from itou.api.insertion.views import OrientationsCountView, OrientationsView
from itou.api.job_application_api.views import JobApplicationSearchView
from itou.api.marche_api.views import MarcheCompanyView
from itou.api.nexus.views import (
    MembershipsView,
    StructuresView,
    SyncCompletedView,
    SyncStartView,
    UsersView,
)
from itou.api.scalar_views import DocumentationSchemaView, ScalarView
from itou.api.siae_api.viewsets import SiaeViewSet
from itou.api.token_auth.views import ObtainAuthToken


# High level app for API
# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "itou.api"

# Using DRF router with viewsets means automatic definition of URL patterns
router = routers.DefaultRouter()
router.register(r"employee-records", EmployeeRecordViewSet, basename="employee-records")
router.register(r"siaes", SiaeViewSet, basename="siaes")

urlpatterns = [
    # OpenAPI
    # See: https://www.django-rest-framework.org/topics/documenting-your-api/
    # OAS 3 YAML schema (downloadable)
    path(
        "oas3/",
        login_not_required(SpectacularAPIView.as_view()),
        name="openapi_schema",
    ),
    # OAS 3 schema restricted to the endpoints of one documentation
    path("oas3/<slug:slug>/", DocumentationSchemaView.as_view(), name="documentation_schema"),
    # API Documentation
    path("documentation/<slug:slug>/", ScalarView.as_view(), name="documentation"),
    # Legacy URLs of the documentation, kept for existing links: the API index lists the documentations.
    path(
        "redoc/",
        login_not_required(RedirectView.as_view(pattern_name="api:index", permanent=True)),
        name="redoc",
    ),
    # TokenAuthentication endpoint to get token from login/password.
    path("token-auth/", ObtainAuthToken.as_view(), name="token-auth"),
    path("embauches-geiq/", GeiqJobApplicationListView.as_view(), name="geiq_jobapplication_list"),
    path("candidats/", ApplicantsView.as_view(), name="applicants-list"),
    path("candidatures/recherche/", JobApplicationSearchView.as_view(), name="job-applications-search"),
    path("data-inclusion/", DataInclusionStructureView.as_view(), name="structures-list"),
    path("marche/", MarcheCompanyView.as_view(), name="marche-company-list"),
    path("nexus/users", UsersView.as_view(), name="nexus-users"),
    path("nexus/structures", StructuresView.as_view(), name="nexus-structures"),
    path("nexus/memberships", MembershipsView.as_view(), name="nexus-memberships"),
    path("nexus/sync-start", SyncStartView.as_view(), name="nexus-sync-start"),
    path("nexus/sync-completed", SyncCompletedView.as_view(), name="nexus-sync-completed"),
    path("insertion/orientations", OrientationsView.as_view(), name="orientations-list"),
    path("insertion/orientations-count", OrientationsCountView.as_view(), name="orientations-count"),
    path("inbound-parsing/reply-webhook", BrevoInboundParsingView.as_view(), name="reply-webhook"),
    *router.urls,
]
