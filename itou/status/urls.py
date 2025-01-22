from django.urls import path

from itou.status import views


app_name = "status"

urlpatterns = [
    path("", views.index, name="index"),
]
