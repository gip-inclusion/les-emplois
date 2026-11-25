from django.urls import path

from itou.www.api import views


app_name = "api"


urlpatterns = [
    path("", views.index, name="index"),
]
