from django.urls import path

from . import views


app_name = "job_seekers_views"

urlpatterns = [
    path("details/<uuid:public_id>", views.JobSeekerDetailView.as_view(), name="details"),
    path("list", views.JobSeekerListView.as_view(), name="list"),
    path("sender/check_nir/<uuid:session_uuid>", views.CheckNIRForSenderView.as_view(), name="check_nir_for_sender"),
    path("sender/check_nir", views.CheckNIRForSenderView.as_view(), name="check_nir_for_sender"),
    path(
        "sender/search-by-email/<uuid:session_uuid>",
        views.SearchByEmailForSenderView.as_view(),
        name="search_by_email",
    ),
    path(
        "sender/create/<uuid:session_uuid>/1",
        views.CreateJobSeekerStep1ForSenderView.as_view(),
        name="create_job_seeker_step_1_for_sender",
    ),
    path(
        "sender/create/<uuid:session_uuid>/2",
        views.CreateJobSeekerStep2ForSenderView.as_view(),
        name="create_job_seeker_step_2_for_sender",
    ),
    path(
        "sender/create/<uuid:session_uuid>/3",
        views.CreateJobSeekerStep3ForSenderView.as_view(),
        name="create_job_seeker_step_3_for_sender",
    ),
    path(
        "sender/create/<uuid:session_uuid>/end",
        views.CreateJobSeekerStepEndForSenderView.as_view(),
        name="create_job_seeker_step_end_for_sender",
    ),
]
