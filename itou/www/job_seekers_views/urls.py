from django.urls import path

from . import views


app_name = "job_seekers_views"

urlpatterns = [
    path("details/<uuid:public_id>", views.JobSeekerDetailView.as_view(), name="details"),
    path("list", views.JobSeekerListView.as_view(), name="list"),
    # For sender
    # TODO(ewen): this URL will change to a new one with a session_uuid instead of a company_pk
    path("<int:company_pk>/sender/check-nir", views.CheckNIRForSenderView.as_view(), name="check_nir_for_sender"),
    # TODO(ewen): this URL will change to a new one without company_pk
    path(
        "<int:company_pk>/sender/search-by-email/<uuid:session_uuid>",
        views.SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_sender",
    ),
    # Direct hire process
    # TODO(ewen): this URL will change to a new one with a session_uuid instead of a company_pk
    path(
        "<int:company_pk>/hire/check-nir",
        views.CheckNIRForSenderView.as_view(),
        name="check_nir_for_hire",
        kwargs={"hire_process": True},
    ),
    # TODO(ewen): this URL will change to a new one without company_pk
    path(
        "<int:company_pk>/hire/search-by-email/<uuid:session_uuid>",
        views.SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_hire",
        kwargs={"hire_process": True},
    ),
    # For job seeker
    # TODO(ewen): this URL will change to a new one with a session_uuid instead of a company_pk
    path(
        "<int:company_pk>/job-seeker/check-nir",
        views.CheckNIRForJobSeekerView.as_view(),
        name="check_nir_for_job_seeker",
    ),
]
