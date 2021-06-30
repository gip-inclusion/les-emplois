from django.urls import include, path
from rest_framework import routers
from rest_framework.authtoken import views as auth_views
from rest_framework.schemas import get_schema_view

from .employee_record_api.viewsets import DummyEmployeeRecordViewSet, EmployeeRecordViewSet


# High level app for API
# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "itou.api"

# Using DRF router with viewsets means automatic definition of utl patterns
router = routers.DefaultRouter()
router.register(r"employee-records", EmployeeRecordViewSet, basename="employee-records")
router.register(r"dummy-employee-records", DummyEmployeeRecordViewSet, basename="dummy-employee-records")

urlpatterns = [
    # TokenAuthentication endpoint to get token from login/password.
    path("token-auth/", auth_views.obtain_auth_token, name="token-auth"),
    # Needed for Browseable API (dev)
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    # OpenAPI / Swagger section
    # See: https://www.django-rest-framework.org/topics/documenting-your-api/
    # OAS 3 YAML schema (downloadable)
    path(
        "oas3/",
        get_schema_view(
            title="API = les emplois",
            version="1.0.0",
            description="Fichier Swagger/OAS3 de définition de l'API emplois.inclusion.beta.gouv.fr",
        ),
        name="openapi_schema",
    ),
]

urlpatterns += router.urls
