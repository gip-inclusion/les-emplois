from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.employee_record.enums import Status
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.test import parse_response_to_soup


def test_wizard(snapshot, client):
    company = CompanyFactory(with_membership=True)
    approval = ApprovalFactory(for_snapshot=True)
    job_application = JobApplicationFactory(
        to_company=company,
        job_seeker=approval.user,
        with_approval=True,
        approval=approval,
    )
    client.force_login(company.members.first())

    start_url = reverse("employee_record_views:add")
    choose_employee_url = reverse("employee_record_views:add", kwargs={"step": "choose-employee"})
    choose_approval_url = reverse("employee_record_views:add", kwargs={"step": "choose-approval"})
    end_url = reverse("employee_record_views:add", kwargs={"step": "done"})

    # Starting the tunnel should redirect to the first step
    assertRedirects(client.get(start_url), choose_employee_url)

    # Submit data for the "choose-employee" step
    # TODO: Figure out why testing manually is OK ("Étape 1/2") but with client it's not ("Étape 1/1")
    # assert str(parse_response_to_soup(client.get(choose_employee_url), selector="#main .s-section")) == snapshot(
    #     name="choose-employee"
    # )
    response = client.post(
        choose_employee_url,
        {"choose-employee-employee": job_application.job_seeker.pk, "add_view-current_step": "choose-employee"},
    )
    assertRedirects(response, choose_approval_url)

    # Submit data for the "choose-approval" step
    soup = parse_response_to_soup(client.get(choose_approval_url), selector="#main .s-section")
    assert soup.find(id="id_choose-approval-approval").option["value"] == str(approval.pk)
    soup.find(id="id_choose-approval-approval").option["value"] = "[PK of Approval]"
    assert str(soup) == snapshot(name="choose-approval")
    response = client.post(
        choose_approval_url,
        {
            "choose-approval-approval": job_application.approval.pk,
            "add_view-current_step": "choose-approval",
        },
    )

    assertRedirects(response, end_url, fetch_redirect_response=False)


def test_done_step_when_the_employee_record_need_to_be_created(client):
    company = CompanyFactory(with_membership=True)
    job_application = JobApplicationFactory(
        to_company=company,
        with_approval=True,
    )
    client.force_login(company.members.first())

    choose_employee_url = reverse("employee_record_views:add", kwargs={"step": "choose-employee"})
    choose_approval_url = reverse("employee_record_views:add", kwargs={"step": "choose-approval"})
    end_url = reverse("employee_record_views:create", kwargs={"job_application_id": job_application.pk})

    client.post(
        choose_employee_url,
        {"choose-employee-employee": job_application.job_seeker.pk, "add_view-current_step": "choose-employee"},
    )
    response = client.post(
        choose_approval_url,
        {
            "choose-approval-approval": job_application.approval.pk,
            "add_view-current_step": "choose-approval",
        },
        follow=True,  # Don't stop to the `done` step
    )

    assertRedirects(response, end_url)


def test_done_step_when_a_new_employee_record_already_exists(client):
    company = CompanyFactory(with_membership=True)
    job_application = JobApplicationFactory(
        to_company=company,
        to_company__use_employee_record=True,
        with_approval=True,
    )
    EmployeeRecordFactory(job_application=job_application, status=Status.NEW)

    client.force_login(company.members.first())

    choose_employee_url = reverse("employee_record_views:add", kwargs={"step": "choose-employee"})
    choose_approval_url = reverse("employee_record_views:add", kwargs={"step": "choose-approval"})
    end_url = (
        reverse("employee_record_views:create", kwargs={"job_application_id": job_application.pk})
        + "?back_url="
        + reverse("employee_record_views:add", kwargs={"step": "choose-employee"})
    )

    client.post(
        choose_employee_url,
        {"choose-employee-employee": job_application.job_seeker.pk, "add_view-current_step": "choose-employee"},
    )

    response = client.post(
        choose_approval_url,
        {
            "choose-approval-approval": job_application.approval.pk,
            "add_view-current_step": "choose-approval",
        },
        follow=True,  # Don't stop to the `done` step
    )

    assertRedirects(response, end_url)


def test_done_step_when_a_other_than_new_employee_record_already_exists(client):
    company = CompanyFactory(with_membership=True)
    job_application = JobApplicationFactory(
        to_company=company,
        to_company__use_employee_record=True,
        with_approval=True,
    )
    employee_record = EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

    client.force_login(company.members.first())

    choose_employee_url = reverse("employee_record_views:add", kwargs={"step": "choose-employee"})
    choose_approval_url = reverse("employee_record_views:add", kwargs={"step": "choose-approval"})
    end_url = reverse("employee_record_views:summary", kwargs={"employee_record_id": employee_record.pk})

    client.post(
        choose_employee_url,
        {"choose-employee-employee": job_application.job_seeker.pk, "add_view-current_step": "choose-employee"},
    )

    response = client.post(
        choose_approval_url,
        {
            "choose-approval-approval": job_application.approval.pk,
            "add_view-current_step": "choose-approval",
        },
        follow=True,  # Don't stop to the `done` step
    )

    assertRedirects(response, end_url)
