from django.urls import path

from itou.www.apply.views import edit_views, list_views, process_views, submit_views
from itou.www.job_seekers_views.views import (
    CheckNIRForJobSeekerView,
    CheckNIRForSenderView,
    SearchByEmailForSenderView,
)


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "apply"

urlpatterns = [
    # Submit.
    path("<int:company_pk>/start", submit_views.StartView.as_view(), name="start"),
    # Submit - sender.
    path(
        "<int:company_pk>/sender/pending_authorization",
        submit_views.PendingAuthorizationForSender.as_view(),
        name="pending_authorization_for_sender",
    ),
    # Ewen: deprecated url. These urls are going to job_seekers_views.views
    path("<int:company_pk>/sender/check_nir", CheckNIRForSenderView.as_view(), name="check_nir_for_sender"),
    # Ewen: deprecated url. These urls are going to job_seekers_views
    path(
        "<int:company_pk>/sender/search-by-email/<uuid:session_uuid>",
        SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_sender",
    ),
    path(
        "<int:company_pk>/sender/create_job_seeker/<uuid:session_uuid>/1",
        submit_views.CreateJobSeekerStep1ForSenderView.as_view(),
        name="create_job_seeker_step_1_for_sender",
    ),
    path(
        "<int:company_pk>/sender/create_job_seeker/<uuid:session_uuid>/2",
        submit_views.CreateJobSeekerStep2ForSenderView.as_view(),
        name="create_job_seeker_step_2_for_sender",
    ),
    path(
        "<int:company_pk>/sender/create_job_seeker/<uuid:session_uuid>/3",
        submit_views.CreateJobSeekerStep3ForSenderView.as_view(),
        name="create_job_seeker_step_3_for_sender",
    ),
    path(
        "<int:company_pk>/sender/create_job_seeker/<uuid:session_uuid>/end",
        submit_views.CreateJobSeekerStepEndForSenderView.as_view(),
        name="create_job_seeker_step_end_for_sender",
    ),
    # Submit - job seeker.
    # Ewen: deprecated url. These urls are going to job_seekers_views.views
    path(
        "<int:company_pk>/job_seeker/check_nir",
        CheckNIRForJobSeekerView.as_view(),
        name="check_nir_for_job_seeker",
    ),
    # Submit - common.
    path(
        "<int:company_pk>/create/<uuid:job_seeker_public_id>/check_job_seeker_info",
        submit_views.CheckJobSeekerInformations.as_view(),
        name="step_check_job_seeker_info",
    ),
    path(
        "<int:company_pk>/create/<uuid:job_seeker_public_id>/check_prev_applications",
        submit_views.CheckPreviousApplications.as_view(),
        name="step_check_prev_applications",
    ),
    path(
        "<int:company_pk>/create/<uuid:job_seeker_public_id>/select_jobs",
        submit_views.ApplicationJobsView.as_view(),
        name="application_jobs",
    ),
    path(
        "<int:company_pk>/create/<uuid:job_seeker_public_id>/eligibility",
        submit_views.ApplicationEligibilityView.as_view(),
        name="application_eligibility",
    ),
    path(
        "<int:company_pk>/create/<uuid:job_seeker_public_id>/geiq_eligibility",
        submit_views.ApplicationGEIQEligibilityView.as_view(),
        name="application_geiq_eligibility",
    ),
    path(
        "<int:company_pk>/create/<uuid:job_seeker_public_id>/resume",
        submit_views.ApplicationResumeView.as_view(),
        name="application_resume",
    ),
    path(
        "<int:company_pk>/application/<uuid:application_pk>/end",
        submit_views.ApplicationEndView.as_view(),
        name="application_end",
    ),
    # Job seeker check/updates
    path(
        "<int:company_pk>/update_job_seeker/<uuid:job_seeker_public_id>/1",
        submit_views.UpdateJobSeekerStep1View.as_view(),
        name="update_job_seeker_step_1",
    ),
    path(
        "<int:company_pk>/update_job_seeker/<uuid:job_seeker_public_id>/2",
        submit_views.UpdateJobSeekerStep2View.as_view(),
        name="update_job_seeker_step_2",
    ),
    path(
        "<int:company_pk>/update_job_seeker/<uuid:job_seeker_public_id>/3",
        submit_views.UpdateJobSeekerStep3View.as_view(),
        name="update_job_seeker_step_3",
    ),
    path(
        "<int:company_pk>/update_job_seeker/<uuid:job_seeker_public_id>/end",
        submit_views.UpdateJobSeekerStepEndView.as_view(),
        name="update_job_seeker_step_end",
    ),
    # Direct hire process
    # Ewen: deprecated url. These urls are going to job_seekers_views.views
    path(
        "<int:company_pk>/hire/check-nir",
        CheckNIRForSenderView.as_view(),
        name="check_nir_for_hire",
        kwargs={"hire_process": True},
    ),
    # Ewen: deprecated url. These urls are going to job_seekers_views
    path(
        "<int:company_pk>/hire/search-by-email/<uuid:session_uuid>",
        SearchByEmailForSenderView.as_view(),
        name="search_by_email_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/create-job-seeker/<uuid:session_uuid>/1",
        submit_views.CreateJobSeekerStep1ForSenderView.as_view(),
        name="create_job_seeker_step_1_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/create-job-seeker/<uuid:session_uuid>/2",
        submit_views.CreateJobSeekerStep2ForSenderView.as_view(),
        name="create_job_seeker_step_2_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/create-job-seeker/<uuid:session_uuid>/3",
        submit_views.CreateJobSeekerStep3ForSenderView.as_view(),
        name="create_job_seeker_step_3_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/create-job-seeker/<uuid:session_uuid>/end",
        submit_views.CreateJobSeekerStepEndForSenderView.as_view(),
        name="create_job_seeker_step_end_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/update-job-seeker/<uuid:job_seeker_public_id>/1",
        submit_views.UpdateJobSeekerStep1View.as_view(),
        name="update_job_seeker_step_1_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/update-job-seeker/<uuid:job_seeker_public_id>/2",
        submit_views.UpdateJobSeekerStep2View.as_view(),
        name="update_job_seeker_step_2_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/update-job-seeker/<uuid:job_seeker_public_id>/3",
        submit_views.UpdateJobSeekerStep3View.as_view(),
        name="update_job_seeker_step_3_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/update-job-seeker/<uuid:job_seeker_public_id>/end",
        submit_views.UpdateJobSeekerStepEndView.as_view(),
        name="update_job_seeker_step_end_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/<uuid:job_seeker_public_id>/check-infos",
        submit_views.CheckJobSeekerInformationsForHire.as_view(),
        name="check_job_seeker_info_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/<uuid:job_seeker_public_id>/check-previous-applications",
        submit_views.CheckPreviousApplications.as_view(),
        name="check_prev_applications_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<int:company_pk>/hire/<uuid:job_seeker_public_id>/eligibility",
        submit_views.eligibility_for_hire,
        name="eligibility_for_hire",
    ),
    path(
        "<int:company_pk>/hire/<uuid:job_seeker_public_id>/geiq-eligibility",
        submit_views.geiq_eligibility_for_hire,
        name="geiq_eligibility_for_hire",
    ),
    path(
        "<int:company_pk>/hire/<uuid:job_seeker_public_id>/geiq-eligibility-criteria",
        submit_views.geiq_eligibility_criteria_for_hire,
        name="geiq_eligibility_criteria_for_hire",
    ),
    path(
        "<int:company_pk>/hire/<uuid:job_seeker_public_id>/confirm",
        submit_views.hire_confirmation,
        name="hire_confirmation",
    ),
    # List.
    path("job_seeker/list", list_views.list_for_job_seeker, name="list_for_job_seeker"),
    path("prescriptions/list", list_views.list_prescriptions, name="list_prescriptions"),
    path("prescriptions/list/exports", list_views.list_prescriptions_exports, name="list_prescriptions_exports"),
    path(
        "prescriptions/list/exports/download",
        list_views.list_prescriptions_exports_download,
        name="list_prescriptions_exports_download",
    ),
    path(
        "prescriptions/list/exports/download/<str:month_identifier>",
        list_views.list_prescriptions_exports_download,
        name="list_prescriptions_exports_download",
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
        "<uuid:job_application_id>/jobseeker/details",
        process_views.details_for_jobseeker,
        name="details_for_jobseeker",
    ),
    path(
        "<uuid:job_application_id>/prescriber/details",
        process_views.details_for_prescriber,
        name="details_for_prescriber",
    ),
    path("<uuid:job_application_id>/siae/details", process_views.details_for_company, name="details_for_company"),
    path("<uuid:job_application_id>/siae/process", process_views.process, name="process"),
    path("<uuid:job_application_id>/siae/eligibility", process_views.eligibility, name="eligibility"),
    path("<uuid:job_application_id>/siae/geiq_eligibility", process_views.geiq_eligibility, name="geiq_eligibility"),
    path(
        "<uuid:job_application_id>/siae/geiq_eligibility_criteria",
        process_views.geiq_eligibility_criteria,
        name="geiq_eligibility_criteria",
    ),
    path(
        "<uuid:job_application_id>/siae/refuse",
        process_views.JobApplicationRefuseView.as_view(url_name="refuse"),
        name="refuse",
    ),
    path(
        "<uuid:job_application_id>/siae/refuse/<slug:step>",
        process_views.JobApplicationRefuseView.as_view(url_name="refuse"),
        name="refuse",
    ),
    path("<uuid:job_application_id>/siae/postpone", process_views.postpone, name="postpone"),
    path("<uuid:job_application_id>/siae/accept", process_views.accept, name="accept"),
    path("<uuid:job_application_id>/siae/cancel", process_views.cancel, name="cancel"),
    path("<uuid:job_application_id>/siae/transfer", process_views.transfer, name="transfer"),
    path(
        "<uuid:job_application_id>/siae/external-transfer/1",
        process_views.JobApplicationExternalTransferStep1View.as_view(),
        name="job_application_external_transfer_step_1",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/1/company/<int:company_pk>",
        process_views.JobApplicationExternalTransferStep1CompanyCardView.as_view(),
        name="job_application_external_transfer_step_1_company_card",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/1/job_description/<int:job_description_id>",
        process_views.JobApplicationExternalTransferStep1JobDescriptionCardView.as_view(),
        name="job_application_external_transfer_step_1_job_description_card",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/2/<int:company_pk>",
        process_views.JobApplicationExternalTransferStep2View.as_view(),
        name="job_application_external_transfer_step_2",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/3/<int:company_pk>",
        process_views.JobApplicationExternalTransferStep3View.as_view(),
        name="job_application_external_transfer_step_3",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/end",
        process_views.JobApplicationExternalTransferStepEndView.as_view(),
        name="job_application_external_transfer_step_end",
    ),
    path(
        "<uuid:job_application_id>/siae/transfer/<int:company_pk>",
        process_views.JobApplicationInternalTranferView.as_view(),
        name="job_application_internal_transfer",
    ),
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
    path(
        "<uuid:job_application_id>/siae/archive",
        edit_views.archive_view,
        name="archive",
        kwargs={"action": "archive"},
    ),
    path(
        "<uuid:job_application_id>/siae/unarchive",
        edit_views.archive_view,
        name="unarchive",
        kwargs={"action": "unarchive"},
    ),
    # Diagoriente
    path(
        "<uuid:job_application_id>/siae/diagoriente/send_invite",
        process_views.send_diagoriente_invite,
        name="send_diagoriente_invite",
    ),
    # HTMX fragments loading
    path(
        "<int:company_pk>/accept/reload_qualification_fields",
        process_views.ReloadQualificationFields.as_view(),
        name="reload_qualification_fields",
    ),
    path(
        "<int:company_pk>/accept/reload_contract_type_and_options",
        process_views.ReloadContractTypeAndOptions.as_view(),
        name="reload_contract_type_and_options",
    ),
    path(
        "<int:company_pk>/accept/reload_job_description_fields",
        process_views.ReloadJobDescriptionFields.as_view(),
        name="reload_job_description_fields",
    ),
    path(
        "<uuid:job_application_id>/rdv-insertion-invite",
        process_views.rdv_insertion_invite,
        name="rdv_insertion_invite",
    ),
    path(
        "<uuid:job_application_id>/rdv_insertion_invite_for_detail",
        process_views.rdv_insertion_invite,
        {"for_detail": True},
        name="rdv_insertion_invite_for_detail",
    ),
]
