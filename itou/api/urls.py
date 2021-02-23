from django.urls import path
from rest_framework.authtoken import views as auth_views

from itou.api import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "api"

urlpatterns = [
    # TokenAuthentication endpoint to get token from login/password.
    path("token-auth/", auth_views.obtain_auth_token, name="token-auth"),
    path("dummy-employee-records/", views.DummyEmployeeRecordList.as_view(), name="dummy-employee-records"),
]
