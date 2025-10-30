from django.urls import path

from itou.www.apply.views import batch_views, edit_views, list_views, process_views, submit_views, transfer_views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "apply"

urlpatterns = [
    # Submit.
    path("<int:company_pk>/start", submit_views.StartView.as_view(), name="start"),
    path(
        "<int:company_pk>/hire",
        submit_views.StartView.as_view(),
        name="start_hire",
        kwargs={"hire_process": True},
    ),
    # Submit - sender.
    path(
        "<uuid:session_uuid>/sender/pending_authorization",
        submit_views.PendingAuthorizationForSender.as_view(),
        name="pending_authorization_for_sender",
    ),
    # Submit - common.
    path(
        "<uuid:session_uuid>/create/check_prev_applications",
        submit_views.CheckPreviousApplications.as_view(),
        name="step_check_prev_applications",
    ),
    path(
        "<uuid:session_uuid>/create/select_jobs",
        submit_views.ApplicationJobsView.as_view(),
        name="application_jobs",
    ),
    path(
        "<uuid:session_uuid>/create/iae-eligibility",
        submit_views.ApplicationIAEEligibilityView.as_view(),
        name="application_iae_eligibility",
    ),
    path(
        "<uuid:session_uuid>/create/geiq_eligibility",
        submit_views.ApplicationGEIQEligibilityView.as_view(),
        name="application_geiq_eligibility",
    ),
    path(
        "<uuid:session_uuid>/create/resume",
        submit_views.ApplicationResumeView.as_view(),
        name="application_resume",
    ),
    path(
        "application/<uuid:application_pk>/end",
        submit_views.ApplicationEndView.as_view(),
        name="application_end",
    ),
    # Direct hire process
    path(
        "<uuid:session_uuid>/hire/check-previous-applications",
        submit_views.CheckPreviousApplications.as_view(),
        name="check_prev_applications_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/iae-eligibility",
        submit_views.IAEEligibilityForHireView.as_view(),
        name="iae_eligibility_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/geiq-eligibility",
        submit_views.GEIQEligibilityForHireView.as_view(),
        name="geiq_eligibility_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/geiq-eligibility-criteria",
        submit_views.GEIQEligiblityCriteriaForHireView.as_view(),
        name="geiq_eligibility_criteria_for_hire",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/job-seeker-infos",
        submit_views.FillJobSeekerInfosForHireView.as_view(),
        name="hire_fill_job_seeker_infos",
        kwargs={"hire_process": True},
    ),
    path(
        "<uuid:session_uuid>/hire/contract",
        submit_views.ContractForHireView.as_view(),
        name="hire_contract",
        kwargs={"hire_process": True},
    ),
    # Legacy view: this will be dropped in a few days
    path(
        "<uuid:session_uuid>/hire/confirm",
        submit_views.HireConfirmationView.as_view(),
        name="hire_confirmation",
        kwargs={"hire_process": True},
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
    path("siae/list/actions", list_views.list_for_siae_actions, name="list_for_siae_actions"),
    path("company/batch/archive", batch_views.archive, name="batch_archive"),
    path("company/batch/postpone", batch_views.postpone, name="batch_postpone"),
    path("company/batch/add-to-pool", batch_views.add_to_pool, name="batch_add_to_pool"),
    path("company/batch/process", batch_views.process, name="batch_process"),
    path("company/batch/refuse", batch_views.refuse, name="batch_refuse"),
    path(
        "company/batch/refuse/<uuid:session_uuid>/<slug:step>",
        batch_views.RefuseWizardView.as_view(),
        name="batch_refuse_steps",
    ),
    path("company/batch/transfer", batch_views.transfer, name="batch_transfer"),
    path("company/batch/unarchive", batch_views.unarchive, name="batch_unarchive"),
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
    path("<uuid:job_application_id>/siae/add-to-pool", process_views.add_to_pool, name="add_to_pool"),
    path(
        "<uuid:job_application_id>/siae/comment",
        process_views.add_comment_for_company,
        name="add_comment_for_company",
    ),
    path(
        "<uuid:job_application_id>/siae/comment/<int:comment_id>/delete",
        process_views.delete_comment_for_company,
        name="delete_comment_for_company",
    ),
    path("<uuid:job_application_id>/siae/process", process_views.process, name="process"),
    path("<uuid:job_application_id>/siae/eligibility", process_views.IAEEligibilityView.as_view(), name="eligibility"),
    path(
        "<uuid:job_application_id>/siae/geiq_eligibility",
        process_views.GEIQEligibilityView.as_view(),
        name="geiq_eligibility",
    ),
    path(
        "<uuid:job_application_id>/siae/geiq_eligibility_criteria",
        process_views.GEIQEligiblityCriteriaView.as_view(),
        name="geiq_eligibility_criteria",
    ),
    path(
        "<uuid:job_application_id>/siae/refuse",
        process_views.start_refuse_wizard,
        name="refuse",
    ),
    path("<uuid:job_application_id>/siae/postpone", process_views.postpone, name="postpone"),
    path("<uuid:job_application_id>/siae/accept", process_views.AcceptView.as_view(), name="accept"),
    path("<uuid:job_application_id>/siae/start-accept", process_views.start_accept_wizard, name="start-accept"),
    path(
        "<uuid:session_uuid>/accept/job-seeker-infos",
        process_views.FillJobSeekerInfosForAcceptView.as_view(),
        name="accept_fill_job_seeker_infos",
    ),
    path(
        "<uuid:session_uuid>/accept/contract",
        process_views.ContractForAcceptView.as_view(),
        name="accept_contract_infos",
    ),
    path("<uuid:job_application_id>/siae/cancel", process_views.cancel, name="cancel"),
    path("<uuid:job_application_id>/siae/transfer", transfer_views.transfer, name="transfer"),
    path(
        "<uuid:job_application_id>/siae/external-transfer/1",
        transfer_views.JobApplicationExternalTransferStep1View.as_view(),
        name="job_application_external_transfer_step_1",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/1/company/<int:company_pk>",
        transfer_views.JobApplicationExternalTransferStep1CompanyCardView.as_view(),
        name="job_application_external_transfer_step_1_company_card",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/1/job_description/<int:job_description_id>",
        transfer_views.JobApplicationExternalTransferStep1JobDescriptionCardView.as_view(),
        name="job_application_external_transfer_step_1_job_description_card",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/2/start_session/<int:company_pk>",
        transfer_views.job_application_external_transfer_start_view,
        name="job_application_external_transfer_start_session",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/2/<uuid:session_uuid>",
        transfer_views.JobApplicationExternalTransferStep2View.as_view(),
        name="job_application_external_transfer_step_2",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/3/<uuid:session_uuid>",
        transfer_views.JobApplicationExternalTransferStep3View.as_view(),
        name="job_application_external_transfer_step_3",
    ),
    path(
        "<uuid:job_application_id>/siae/external-transfer/end",
        transfer_views.JobApplicationExternalTransferStepEndView.as_view(),
        name="job_application_external_transfer_step_end",
    ),
    path(
        "<uuid:job_application_id>/siae/transfer/<int:company_pk>",
        transfer_views.JobApplicationInternalTransferView.as_view(),
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
        "<int:company_pk>/accept/<uuid:job_seeker_public_id>/reload_qualification_fields",
        process_views.ReloadQualificationFields.as_view(),
        name="reload_qualification_fields",
    ),
    path(
        "<int:company_pk>/accept/<uuid:job_seeker_public_id>/reload_contract_type_and_options",
        process_views.ReloadContractTypeAndOptions.as_view(),
        name="reload_contract_type_and_options",
    ),
    path(
        "<int:company_pk>/accept/<uuid:job_seeker_public_id>/reload_job_description_fields",
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
