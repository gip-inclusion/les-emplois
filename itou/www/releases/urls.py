from django.urls import path

from itou.www.releases import views


app_name = "releases"


urlpatterns = [
    path("", views.releases, name="list"),
]
