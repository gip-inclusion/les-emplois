from django.urls import path

from itou.www.apply.views import edit_views, list_views, process_views, submit_views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "apply"

urlpatterns = [
    # Submit.
    path("<int:siae_pk>/start", submit_views.StartView.as_view(), name="start"),
    # Submit - sender.
    path(
        "<int:siae_pk>/sender/pending_authorization",
        submit_views.PendingAuthorizationForSender.as_view(),
        name="pending_authorization_for_sender",
    ),
    path("<int:siae_pk>/sender/check_nir", submit_views.CheckNIRForSenderView.as_view(), name="check_nir_for_sender"),
    path(
        "<int:siae_pk>/sender/search-by-email/<uuid:session_uuid>",
        submit_views.SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_sender",
    ),
    path(
        "<int:siae_pk>/sender/create_job_seeker/<uuid:session_uuid>/1",
        submit_views.CreateJobSeekerStep1ForSenderView.as_view(),
        name="create_job_seeker_step_1_for_sender",
    ),
    path(
        "<int:siae_pk>/sender/create_job_seeker/<uuid:session_uuid>/2",
        submit_views.CreateJobSeekerStep2ForSenderView.as_view(),
        name="create_job_seeker_step_2_for_sender",
    ),
    path(
        "<int:siae_pk>/sender/create_job_seeker/<uuid:session_uuid>/3",
        submit_views.CreateJobSeekerStep3ForSenderView.as_view(),
        name="create_job_seeker_step_3_for_sender",
    ),
    path(
        "<int:siae_pk>/sender/create_job_seeker/<uuid:session_uuid>/end",
        submit_views.CreateJobSeekerStepEndForSenderView.as_view(),
        name="create_job_seeker_step_end_for_sender",
    ),
    # Submit - job seeker.
    path(
        "<int:siae_pk>/job_seeker/check_nir",
        submit_views.CheckNIRForJobSeekerView.as_view(),
        name="check_nir_for_job_seeker",
    ),
    # Submit - common.
    path(
        "<int:siae_pk>/create/<int:job_seeker_pk>/check_job_seeker_info",
        submit_views.CheckJobSeekerInformations.as_view(),
        name="step_check_job_seeker_info",
    ),
    path(
        "<int:siae_pk>/create/<int:job_seeker_pk>/check_prev_applications",
        submit_views.CheckPreviousApplications.as_view(),
        name="step_check_prev_applications",
    ),
    path(
        "<int:siae_pk>/create/<int:job_seeker_pk>/select_jobs",
        submit_views.ApplicationJobsView.as_view(),
        name="application_jobs",
    ),
    path(
        "<int:siae_pk>/create/<int:job_seeker_pk>/eligibility",
        submit_views.ApplicationEligibilityView.as_view(),
        name="application_eligibility",
    ),
    path(
        "<int:siae_pk>/create/<int:job_seeker_pk>/geiq_eligibility",
        submit_views.ApplicationGEIQEligibilityView.as_view(),
        name="application_geiq_eligibility",
    ),
    path(
        "<int:siae_pk>/create/<int:job_seeker_pk>/resume",
        submit_views.ApplicationResumeView.as_view(),
        name="application_resume",
    ),
    path(
        "<int:siae_pk>/application/<uuid:application_pk>/end",
        submit_views.ApplicationEndView.as_view(),
        name="application_end",
    ),
    # Job seeker check/updates
    path(
        "<int:siae_pk>/update_job_seeker/<int:job_seeker_pk>/1",
        submit_views.UpdateJobSeekerStep1View.as_view(),
        name="update_job_seeker_step_1",
    ),
    path(
        "<int:siae_pk>/update_job_seeker/<int:job_seeker_pk>/2",
        submit_views.UpdateJobSeekerStep2View.as_view(),
        name="update_job_seeker_step_2",
    ),
    path(
        "<int:siae_pk>/update_job_seeker/<int:job_seeker_pk>/3",
        submit_views.UpdateJobSeekerStep3View.as_view(),
        name="update_job_seeker_step_3",
    ),
    path(
        "<int:siae_pk>/update_job_seeker/<int:job_seeker_pk>/end",
        submit_views.UpdateJobSeekerStepEndView.as_view(),
        name="update_job_seeker_step_end",
    ),
    # Direct hire process
    path(
        "<int:siae_pk>/hire/check-nir",
        submit_views.CheckNIRForSenderView.as_view(),
        name="check_nir_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/search-by-email/<uuid:session_uuid>",
        submit_views.SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/create-job-seeker/<uuid:session_uuid>/1",
        submit_views.CreateJobSeekerStep1ForSenderView.as_view(),
        name="create_job_seeker_step_1_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/create-job-seeker/<uuid:session_uuid>/2",
        submit_views.CreateJobSeekerStep2ForSenderView.as_view(),
        name="create_job_seeker_step_2_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/create-job-seeker/<uuid:session_uuid>/3",
        submit_views.CreateJobSeekerStep3ForSenderView.as_view(),
        name="create_job_seeker_step_3_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/create-job-seeker/<uuid:session_uuid>/end",
        submit_views.CreateJobSeekerStepEndForSenderView.as_view(),
        name="create_job_seeker_step_end_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/update-job-seeker/<int:job_seeker_pk>/1",
        submit_views.UpdateJobSeekerStep1View.as_view(),
        name="update_job_seeker_step_1_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/update-job-seeker/<int:job_seeker_pk>/2",
        submit_views.UpdateJobSeekerStep2View.as_view(),
        name="update_job_seeker_step_2_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/update-job-seeker/<int:job_seeker_pk>/3",
        submit_views.UpdateJobSeekerStep3View.as_view(),
        name="update_job_seeker_step_3_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/update-job-seeker/<int:job_seeker_pk>/end",
        submit_views.UpdateJobSeekerStepEndView.as_view(),
        name="update_job_seeker_step_end_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/<int:job_seeker_pk>/check-infos",
        submit_views.CheckJobSeekerInformationsForHire.as_view(),
        name="check_job_seeker_info_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/<int:job_seeker_pk>/check-previous-applications",
        submit_views.CheckPreviousApplications.as_view(),
        name="check_prev_applications_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:siae_pk>/hire/<int:job_seeker_pk>/eligibility",
        submit_views.eligibility_for_hire,
        name="eligibility_for_hire",
    ),
    path(
        "<int:siae_pk>/hire/<int:job_seeker_pk>/geiq-eligibility",
        submit_views.geiq_eligibility_for_hire,
        name="geiq_eligibility_for_hire",
    ),
    path(
        "<int:siae_pk>/hire/<int:job_seeker_pk>/geiq-eligibility-criteria",
        submit_views.geiq_eligibility_criteria_for_hire,
        name="geiq_eligibility_criteria_for_hire",
    ),
    path(
        "<int:siae_pk>/hire/<int:job_seeker_pk>/confirm",
        submit_views.hire_confirmation,
        name="hire_confirmation",
    ),
    # List.
    path("job_seeker/list", list_views.list_for_job_seeker, name="list_for_job_seeker"),
    path("prescriber/list", list_views.list_for_prescriber, name="list_for_prescriber"),
    path("prescriber/list/exports", list_views.list_for_prescriber_exports, name="list_for_prescriber_exports"),
    path(
        "prescriber/list/exports/download",
        list_views.list_for_prescriber_exports_download,
        name="list_for_prescriber_exports_download",
    ),
    path(
        "prescriber/list/exports/download/<str:month_identifier>",
        list_views.list_for_prescriber_exports_download,
        name="list_for_prescriber_exports_download",
    ),
    path("siae/list", list_views.list_for_siae, name="list_for_siae"),
    path("siae/list/exports", list_views.list_for_siae_exports, name="list_for_siae_exports"),
    path(
        "siae/list/exports/download",
        list_views.list_for_siae_exports_download,
        name="list_for_siae_exports_download",
    ),
    path(
        "siae/list/exports/download/<str:month_identifier>",
        list_views.list_for_siae_exports_download,
        name="list_for_siae_exports_download",
    ),
    # Process.
    path(
        "<uuid:job_application_id>/prescriber/details",
        process_views.details_for_prescriber,
        name="details_for_prescriber",
    ),
    path("<uuid:job_application_id>/siae/details", process_views.details_for_siae, name="details_for_siae"),
    path("<uuid:job_application_id>/siae/process", process_views.process, name="process"),
    path("<uuid:job_application_id>/siae/eligibility", process_views.eligibility, name="eligibility"),
    path("<uuid:job_application_id>/siae/geiq_eligibility", process_views.geiq_eligibility, name="geiq_eligibility"),
    path(
        "<uuid:job_application_id>/siae/geiq_eligibility_criteria",
        process_views.geiq_eligibility_criteria,
        name="geiq_eligibility_criteria",
    ),
    path("<uuid:job_application_id>/siae/refuse", process_views.refuse, name="refuse"),
    path("<uuid:job_application_id>/siae/postpone", process_views.postpone, name="postpone"),
    path("<uuid:job_application_id>/siae/accept", process_views.accept, name="accept"),
    path("<uuid:job_application_id>/siae/cancel", process_views.cancel, name="cancel"),
    path("<uuid:job_application_id>/siae/archive", process_views.archive, name="archive"),
    path("<uuid:job_application_id>/siae/transfer", process_views.transfer, name="transfer"),
    path(
        "<uuid:job_application_id>/siae/prior-action/add",
        process_views.add_or_modify_prior_action,
        name="add_prior_action",
    ),
    path(
        "<uuid:job_application_id>/siae/prior-action/<int:prior_action_id>",
        process_views.add_or_modify_prior_action,
        name="modify_prior_action",
    ),
    path(
        "<uuid:job_application_id>/siae/prior-action/<int:prior_action_id>/delete",
        process_views.delete_prior_action,
        name="delete_prior_action",
    ),
    # Variant of accept process (employer does not need an approval)
    path(
        "<uuid:job_application_id>/siae/edit_contract_start_date",
        edit_views.edit_contract_start_date,
        name="edit_contract_start_date",
    ),
    # HTMX fragments loading
    # TODO(xfernandez): remove the job_application_id version in a week
    path(
        "<uuid:job_application_id>/accept/reload_qualification_fields",
        process_views.ReloadQualificationFields.as_view(),
        name="reload_qualification_fields",
    ),
    path(
        "<uuid:job_application_id>/accept/reload_contract_type_and_options",
        process_views.ReloadContractTypeAndOptions.as_view(),
        name="reload_contract_type_and_options",
    ),
    path(
        "<int:siae_pk>/accept/reload_qualification_fields",
        process_views.ReloadQualificationFields.as_view(),
        name="reload_qualification_fields",
    ),
    path(
        "<int:siae_pk>/accept/reload_contract_type_and_options",
        process_views.ReloadContractTypeAndOptions.as_view(),
        name="reload_contract_type_and_options",
    ),
    path(
        "<siae_pk>/accept/reload_job_description_fields",
        process_views.ReloadJobDescriptionFields.as_view(),
        name="reload_job_description_fields",
    ),
]
