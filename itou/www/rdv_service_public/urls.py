from django.urls import path

from itou.www.rdv_service_public import views


app_name = "rdv_service_public"

urlpatterns = [
    path("<uuid:job_application_id>/propose-appointment", views.propose_appointment, name="propose_appointment"),
    path("oauth/callback", views.oauth_callback, name="oauth_callback"),
]
