from django.urls import path

from itou.www.apply.views import list_views, process_views, submit_views

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "apply"

urlpatterns = [
    # Submit.
    path("<int:siae_pk>/start", submit_views.start, name="start"),
    path("<int:siae_pk>/step_sender", submit_views.step_sender, name="step_sender"),
    path(
        "<int:siae_pk>/step_job_seeker",
        submit_views.step_job_seeker,
        name="step_job_seeker",
    ),
    path(
        "<int:siae_pk>/step_check_job_seeker_info",
        submit_views.step_check_job_seeker_info,
        name="step_check_job_seeker_info",
    ),
    path(
        "<int:siae_pk>/step_create_job_seeker",
        submit_views.step_create_job_seeker,
        name="step_create_job_seeker",
    ),
    path(
        "<int:siae_pk>/step_check_prev_applications",
        submit_views.step_check_prev_applications,
        name="step_check_prev_applications",
    ),
    path(
        "<int:siae_pk>/step_eligibility",
        submit_views.step_eligibility,
        name="step_eligibility",
    ),
    path(
        "<int:siae_pk>/step_application",
        submit_views.step_application,
        name="step_application",
    ),
    # List.
    path("job_seeker/list", list_views.list_for_job_seeker, name="list_for_job_seeker"),
    path("prescriber/list", list_views.list_for_prescriber, name="list_for_prescriber"),
    path("siae/list", list_views.list_for_siae, name="list_for_siae"),
    # Process.
    path(
        "<uuid:job_application_id>/siae/details",
        process_views.details_for_siae,
        name="details_for_siae",
    ),
    path(
        "<uuid:job_application_id>/siae/process", process_views.process, name="process"
    ),
    path(
        "<uuid:job_application_id>/siae/eligibility",
        process_views.eligibility,
        name="eligibility",
    ),
    path("<uuid:job_application_id>/siae/refuse", process_views.refuse, name="refuse"),
    path(
        "<uuid:job_application_id>/siae/postpone",
        process_views.postpone,
        name="postpone",
    ),
    path("<uuid:job_application_id>/siae/accept", process_views.accept, name="accept"),
]
