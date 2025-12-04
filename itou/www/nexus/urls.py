from django.urls import path
from itoutils.django.nexus.views import auto_login


app_name = "nexus"

urlpatterns = [
    path("auto-login", auto_login, name="auto_login"),
    # There will soon be more views here
]
