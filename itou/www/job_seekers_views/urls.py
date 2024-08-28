from django.urls import path

from . import views


app_name = "job_seekers_views"

urlpatterns = [
    path("details/<uuid:public_id>", views.JobSeekerDetailView.as_view(), name="details"),
    path("list", views.JobSeekerListView.as_view(), name="list"),
]
