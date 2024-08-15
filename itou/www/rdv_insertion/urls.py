from django.urls import path

from itou.www.rdv_insertion import views


app_name = "rdv_insertion"

urlpatterns = [
    path("webhook", views.webhook, name="webhook"),
]
