from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView
from rest_framework import routers
from rest_framework.authtoken import views as auth_views

from itou.api.data_inclusion_api.views import DataInclusionStructureView

from .applicants_api.views import ApplicantsView
from .employee_record_api.viewsets import (
    DummyEmployeeRecordViewSet,
    EmployeeRecordUpdateNotificationViewSet,
    EmployeeRecordViewSet,
)
from .siae_api.viewsets import SiaeViewSet


# High level app for API
# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "itou.api"

# Using DRF router with viewsets means automatic definition of utl patterns
router = routers.DefaultRouter()
router.register(r"employee-records", EmployeeRecordViewSet, basename="employee-records")
router.register(
    r"employee-record-notifications",
    EmployeeRecordUpdateNotificationViewSet,
    basename="employee-record-notifications",
)
router.register(r"dummy-employee-records", DummyEmployeeRecordViewSet, basename="dummy-employee-records")
router.register(r"siaes", SiaeViewSet, basename="siaes")

urlpatterns = [
    # TokenAuthentication endpoint to get token from login/password.
    path("token-auth/", auth_views.obtain_auth_token, name="token-auth"),
    # Needed for Browseable API (dev)
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    # OpenAPI
    # See: https://www.django-rest-framework.org/topics/documenting-your-api/
    # OAS 3 YAML schema (downloadable)
    path(
        "oas3/",
        SpectacularAPIView.as_view(),
        name="openapi_schema",
    ),
    path(
        "redoc/",
        SpectacularRedocView.as_view(url_name="v1:openapi_schema"),
        name="redoc",
    ),
]

urlpatterns += router.urls

urlpatterns += [
    path("structures/", DataInclusionStructureView.as_view(), name="structures-list"),
    path("candidats/", ApplicantsView.as_view(), name="applicants-list"),
]
