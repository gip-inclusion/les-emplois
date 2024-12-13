from django.urls import path

from . import views


app_name = "job_seekers_views"

urlpatterns = [
    path("details/<uuid:public_id>", views.JobSeekerDetailView.as_view(), name="details"),
    path("list", views.JobSeekerListView.as_view(), name="list"),
    # For sender
    path("<uuid:session_uuid>/sender/check-nir", views.CheckNIRForSenderView.as_view(), name="check_nir_for_sender"),
    path(
        "<uuid:session_uuid>/sender/search-by-email",
        views.SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_sender",
    ),
    path(
        "<uuid:session_uuid>/sender/create/1",
        views.CreateJobSeekerStep1ForSenderView.as_view(),
        name="create_job_seeker_step_1_for_sender",
    ),
    path(
        "<uuid:session_uuid>/sender/create/2",
        views.CreateJobSeekerStep2ForSenderView.as_view(),
        name="create_job_seeker_step_2_for_sender",
    ),
    path(
        "<uuid:session_uuid>/sender/create/3",
        views.CreateJobSeekerStep3ForSenderView.as_view(),
        name="create_job_seeker_step_3_for_sender",
    ),
    path(
        "<uuid:session_uuid>/sender/create/end",
        views.CreateJobSeekerStepEndForSenderView.as_view(),
        name="create_job_seeker_step_end_for_sender",
    ),
    # Direct hire process
    path(
        "<uuid:session_uuid>/hire/check-nir",
        views.CheckNIRForSenderView.as_view(),
        name="check_nir_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/search-by-email",
        views.SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/create/1",
        views.CreateJobSeekerStep1ForSenderView.as_view(),
        name="create_job_seeker_step_1_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/create/2",
        views.CreateJobSeekerStep2ForSenderView.as_view(),
        name="create_job_seeker_step_2_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/create/3",
        views.CreateJobSeekerStep3ForSenderView.as_view(),
        name="create_job_seeker_step_3_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/create/end",
        views.CreateJobSeekerStepEndForSenderView.as_view(),
        name="create_job_seeker_step_end_for_hire",
        kwargs={"hire_process": True},
    ),
    # TODO(ewen): deprecated URLs
    path(
        "<int:company_pk>/hire/update/<uuid:job_seeker_public_id>/1",
        views.DeprecatedUpdateJobSeekerStep1View.as_view(),
        name="update_job_seeker_step_1_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/update/<uuid:job_seeker_public_id>/2",
        views.DeprecatedUpdateJobSeekerStep2View.as_view(),
        name="update_job_seeker_step_2_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/update/<uuid:job_seeker_public_id>/3",
        views.DeprecatedUpdateJobSeekerStep3View.as_view(),
        name="update_job_seeker_step_3_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/update/<uuid:job_seeker_public_id>/end",
        views.DeprecatedUpdateJobSeekerStepEndView.as_view(),
        name="update_job_seeker_step_end_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/<uuid:job_seeker_public_id>/check-infos",
        views.CheckJobSeekerInformationsForHire.as_view(),
        name="check_job_seeker_info_for_hire",
        kwargs={"hire_process": True},
    ),
    # For job seeker
    path(
        "<uuid:session_uuid>/job-seeker/check-nir",
        views.CheckNIRForJobSeekerView.as_view(),
        name="check_nir_for_job_seeker",
    ),
    # Job seeker check/updates
    path(
        "update/start",
        views.UpdateJobSeekerStartView.as_view(),
        name="update_job_seeker_start",
    ),
    path(
        "update/<uuid:session_uuid>/1",
        views.UpdateJobSeekerStep1View.as_view(),
        name="update_job_seeker_step_1",
    ),
    path(
        "update/<uuid:session_uuid>/2",
        views.UpdateJobSeekerStep2View.as_view(),
        name="update_job_seeker_step_2",
    ),
    path(
        "update/<uuid:session_uuid>/3",
        views.UpdateJobSeekerStep3View.as_view(),
        name="update_job_seeker_step_3",
    ),
    path(
        "update/<uuid:session_uuid>/end",
        views.UpdateJobSeekerStepEndView.as_view(),
        name="update_job_seeker_step_end",
    ),
    # TODO(ewen): deprecated URLs
    path(
        "<int:company_pk>/update/<uuid:job_seeker_public_id>/1",
        views.DeprecatedUpdateJobSeekerStep1View.as_view(),
        name="update_job_seeker_step_1",
    ),
    path(
        "<int:company_pk>/update/<uuid:job_seeker_public_id>/2",
        views.DeprecatedUpdateJobSeekerStep2View.as_view(),
        name="update_job_seeker_step_2",
    ),
    path(
        "<int:company_pk>/update/<uuid:job_seeker_public_id>/3",
        views.DeprecatedUpdateJobSeekerStep3View.as_view(),
        name="update_job_seeker_step_3",
    ),
    path(
        "<int:company_pk>/update/<uuid:job_seeker_public_id>/end",
        views.DeprecatedUpdateJobSeekerStepEndView.as_view(),
        name="update_job_seeker_step_end",
    ),
    # Common
    path(
        "<int:company_pk>/create/<uuid:job_seeker_public_id>/check-infos",
        views.CheckJobSeekerInformations.as_view(),
        name="check_job_seeker_info",
    ),
]
