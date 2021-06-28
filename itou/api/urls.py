from django.urls import include, path, re_path
from django.views.generic import TemplateView
from rest_framework import routers
from rest_framework.authtoken import views as auth_views
from rest_framework.schemas import get_schema_view

from .employee_record_api.viewsets import EmployeeRecordViewSet
from .views import DummyEmployeeRecordList


# Using DRF router means automatic definition for list or retrieve actions
router = routers.DefaultRouter()
router.register(r"employee-records", EmployeeRecordViewSet, basename="employee-records")

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "itou.api"

urlpatterns = [
    # TokenAuthentication endpoint to get token from login/password.
    path("token-auth/", auth_views.obtain_auth_token, name="token-auth"),
    # Demo / dummy endpoint
    path("dummy-employee-records/", DummyEmployeeRecordList.as_view(), name="dummy-employee-records"),
    # OpenAPI / Swagger
    # See: https://www.django-rest-framework.org/topics/documenting-your-api/
    path(
        "openapi/",
        get_schema_view(title="API = les emplois", version="1.0.0", description="Test"),
        name="openapi_schema",
    ),
    path(
        "swagger-ui/",
        TemplateView.as_view(template_name="api/openapi.html", extra_context={"schema_url": "v1:openapi_schema"}),
        name="swagger-ui",
    ),
]

urlpatterns += router.urls
