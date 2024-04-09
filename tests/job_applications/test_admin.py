from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertFormError, assertMessages

from itou.employee_record import models as employee_record_models
from itou.job_applications import models
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from tests.employee_record import factories as employee_record_factories
from tests.job_applications import factories
from tests.users.factories import JobSeekerFactory


def test_create_employee_record(admin_client):
    job_application = factories.JobApplicationFactory(
        state=models.JobApplicationState.ACCEPTED,
        with_approval=True,
    )

    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_changelist"),
        {
            "action": "create_employee_record",
            helpers.ACTION_CHECKBOX_NAME: [job_application.pk],
        },
    )

    employee_record = employee_record_models.EmployeeRecord.objects.get()
    assert employee_record.job_application == job_application

    url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.pk])
    assertMessages(
        response,
        [messages.Message(messages.SUCCESS, f'1 fiche salarié créée : <a href="{url}">{employee_record.pk}</a>')],
    )


def test_create_employee_record_when_it_already_exists(admin_client):
    employee_record = employee_record_factories.EmployeeRecordFactory()
    job_application = employee_record.job_application

    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_changelist"),
        {
            "action": "create_employee_record",
            helpers.ACTION_CHECKBOX_NAME: [job_application.pk],
        },
    )

    url = reverse("admin:job_applications_jobapplication_change", args=[job_application.pk])
    assertMessages(
        response,
        [messages.Message(messages.WARNING, f'1 candidature ignorée : <a href="{url}">{job_application.pk}</a>')],
    )


def test_create_job_application_does_not_crash(admin_client):
    job_seeker = JobSeekerFactory()
    company = CompanyFactory()
    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_add"),
        {
            "state": "new",
            "job_seeker": job_seeker.pk,
            "to_company": company.pk,
            "sender_kind": "prescriber",
            "sender_company": "invalid value that should have been a pk",
        },
    )
    assertContains(response, "Corrigez les erreurs ci-dessous")
    assertContains(response, "Emetteur prescripteur manquant")


def test_check_inconsistency_check(admin_client):
    consistent_application = factories.JobApplicationFactory()

    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [consistent_application.pk],
        },
        follow=True,
    )
    assertContains(response, "Aucune incohérence trouvée")

    inconsistent_application_1 = factories.JobApplicationFactory(with_approval=True)
    inconsistent_application_1.approval.user = JobSeekerFactory()
    inconsistent_application_1.approval.save()

    inconsistent_application_2 = factories.JobApplicationFactory(with_approval=True)
    inconsistent_application_2.eligibility_diagnosis.job_seeker = JobSeekerFactory()
    inconsistent_application_2.eligibility_diagnosis.save()

    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [
                consistent_application.pk,
                inconsistent_application_1.pk,
                inconsistent_application_2.pk,
            ],
        },
        follow=True,
    )
    assertMessages(
        response,
        [
            messages.Message(
                messages.WARNING,
                (
                    "2 objets incohérents: <ul>"
                    '<li class="warning">'
                    f'<a href="/admin/job_applications/jobapplication/{inconsistent_application_1.pk}/change/">'
                    f"candidature - {inconsistent_application_1.pk}"
                    "</a>: Candidature liée au PASS IAE d&#x27;un autre candidat</li>"
                    '<li class="warning">'
                    f'<a href="/admin/job_applications/jobapplication/{inconsistent_application_2.pk}/change/">'
                    f"candidature - {inconsistent_application_2.pk}"
                    "</a>: Candidature liée au diagnostic d&#x27;un autre candidat</li>"
                    "</ul>"
                ),
            )
        ],
    )


JOB_APPLICATION_FORMSETS_PAYLOAD = {
    "JobApplication_selected_jobs-TOTAL_FORMS": "1",
    "JobApplication_selected_jobs-INITIAL_FORMS": "0",
    "JobApplication_selected_jobs-MIN_NUM_FORMS": "0",
    "JobApplication_selected_jobs-MAX_NUM_FORMS": "1000",
    "JobApplication_selected_jobs-0-id": "",
    "JobApplication_selected_jobs-0-jobapplication": "",
    "JobApplication_selected_jobs-0-jobdescription": "",
    "JobApplication_selected_jobs-__prefix__-id": "",
    "JobApplication_selected_jobs-__prefix__-jobapplication": "",
    "JobApplication_selected_jobs-__prefix__-jobdescription": "",
    "prior_actions-TOTAL_FORMS": "0",
    "prior_actions-INITIAL_FORMS": "0",
    "prior_actions-MIN_NUM_FORMS": "0",
    "prior_actions-MAX_NUM_FORMS": "0",
    "logs-TOTAL_FORMS": "0",
    "logs-INITIAL_FORMS": "0",
    "logs-MIN_NUM_FORMS": "0",
    "logs-MAX_NUM_FORMS": "0",
    "utils-uuidsupportremark-content_type-object_id-TOTAL_FORMS": "1",
    "utils-uuidsupportremark-content_type-object_id-INITIAL_FORMS": "0",
    "utils-uuidsupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
    "utils-uuidsupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
    "utils-uuidsupportremark-content_type-object_id-0-remark": "",
    "utils-uuidsupportremark-content_type-object_id-0-id": "",
    "utils-uuidsupportremark-content_type-object_id-__prefix__-remark": "",
    "utils-uuidsupportremark-content_type-object_id-__prefix__-id": "",
}


def test_create_accepted_job_application(admin_client):
    job_seeker = JobSeekerFactory()
    company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
    employer = company.members.first()
    post_data = {
        "state": "accepted",
        "job_seeker": job_seeker.pk,
        "to_company": company.pk,
        "sender_kind": "employer",
        "sender_company": company.pk,
        "sender": employer.pk,
        # Formsets to please django admin
        **JOB_APPLICATION_FORMSETS_PAYLOAD,
    }
    response = admin_client.post(reverse("admin:job_applications_jobapplication_add"), post_data)
    assert response.status_code == 200
    assertFormError(
        response.context["adminform"].form,
        "hiring_start_at",
        "Ce champ est obligatoire pour les candidatures acceptées.",
    )
    assertFormError(
        response.context["adminform"].form,
        None,
        (
            "Un diagnostic d'éligibilité valide pour ce candidat "
            "et cette SIAE est obligatoire pour pouvoir créer un PASS IAE."
        ),
    )

    # Retry with the mandatory date
    post_data["hiring_start_at"] = timezone.localdate()
    # and make sure a diagnosis exists
    EligibilityDiagnosisFactory(job_seeker=job_seeker)
    response = admin_client.post(reverse("admin:job_applications_jobapplication_add"), post_data)
    assert response.status_code == 302

    job_app = models.JobApplication.objects.get()
    assert job_app.state.is_accepted
    assert job_app.logs.count() == 2  # new->processing & processing->accepted
    assert job_app.approval


def test_accept_existing_job_application(admin_client):
    job_application = factories.JobApplicationFactory(
        eligibility_diagnosis=None,
        to_company__subject_to_eligibility=True,
        state=models.JobApplicationState.REFUSED,
    )
    change_url = reverse("admin:job_applications_jobapplication_change", args=[job_application.pk])
    post_data = {
        "state": "accepted",
        "job_seeker": job_application.job_seeker.pk,
        "to_company": job_application.to_company.pk,
        "sender_kind": job_application.sender_kind,
        "sender": job_application.sender.pk,
        # Formsets to please django admin
        **JOB_APPLICATION_FORMSETS_PAYLOAD,
    }
    response = admin_client.post(change_url, post_data)
    assert response.status_code == 200
    assertFormError(
        response.context["adminform"].form,
        "hiring_start_at",
        "Ce champ est obligatoire pour les candidatures acceptées.",
    )
    assertFormError(
        response.context["adminform"].form,
        None,
        (
            "Un diagnostic d'éligibilité valide pour ce candidat "
            "et cette SIAE est obligatoire pour pouvoir créer un PASS IAE."
        ),
    )

    # Retry with the mandatory date
    post_data["hiring_start_at"] = timezone.localdate()
    # and make sure a diagnosis exists
    EligibilityDiagnosisFactory(job_seeker=job_application.job_seeker)
    response = admin_client.post(change_url, post_data)
    assert response.status_code == 302

    job_app = models.JobApplication.objects.get()
    assert job_app.state.is_accepted
    assert job_app.logs.count() == 1  # refused->accepted
    assert job_app.approval


def test_create_accepted_job_application_not_subject_to_eligibility(admin_client):
    job_seeker = JobSeekerFactory()
    company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
    post_data = {
        "state": "accepted",
        "job_seeker": job_seeker.pk,
        "to_company": company.pk,
        "sender_kind": "employer",
        "sender_company": company.pk,
        "sender": company.members.first().pk,
        # Formsets to please django admin
        **JOB_APPLICATION_FORMSETS_PAYLOAD,
    }
    response = admin_client.post(reverse("admin:job_applications_jobapplication_add"), post_data)
    assert response.status_code == 200
    assertFormError(
        response.context["adminform"].form,
        "hiring_start_at",
        "Ce champ est obligatoire pour les candidatures acceptées.",
    )

    # Retry with the mandatory date
    post_data["hiring_start_at"] = timezone.localdate()
    response = admin_client.post(reverse("admin:job_applications_jobapplication_add"), post_data)
    assert response.status_code == 302

    job_app = models.JobApplication.objects.get()
    assert job_app.state.is_accepted
    assert job_app.logs.count() == 2  # new->processing & processing->accepted
    assert job_app.approval is None


def test_create_accepted_job_application_for_job_seeker_with_approval(admin_client):
    # Create an approval with a diagnosis that would not be valid for the other company
    # (if the approval didn't exist)
    existing_approval = ApprovalFactory(eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory())
    job_seeker = existing_approval.user
    company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
    post_data = {
        "state": "accepted",
        "job_seeker": job_seeker.pk,
        "to_company": company.pk,
        "sender_kind": "employer",
        "sender_company": company.pk,
        "sender": company.members.first().pk,
        # Formsets to please django admin
        **JOB_APPLICATION_FORMSETS_PAYLOAD,
    }
    response = admin_client.post(reverse("admin:job_applications_jobapplication_add"), post_data)
    assert response.status_code == 200
    assertFormError(
        response.context["adminform"].form,
        "hiring_start_at",
        "Ce champ est obligatoire pour les candidatures acceptées.",
    )

    # Retry with the mandatory date
    post_data["hiring_start_at"] = timezone.localdate()
    response = admin_client.post(reverse("admin:job_applications_jobapplication_add"), post_data)
    assert response.status_code == 302

    job_app = models.JobApplication.objects.get()
    assert job_app.state.is_accepted
    assert job_app.logs.count() == 2  # new->processing & processing->accepted
    assert job_app.approval == existing_approval
