import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.employee_record.enums import Status
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup


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
    with assertSnapshotQueries(snapshot):
        assertRedirects(client.get(start_url), choose_employee_url)

    # Submit data for the "choose-employee" step
    assert str(
        parse_response_to_soup(
            client.get(choose_employee_url),
            selector="#main .s-section",
            replace_in_attr=[
                (
                    "id",
                    f"id_company_{company.pk}_add_employee_record-current_step",
                    "id_company_[PK of Company]_add_employee_record-current_step",
                ),
                (
                    "name",
                    f"company_{company.pk}_add_employee_record-current_step",
                    "company_[PK of Company]_add_employee_record-current_step",
                ),
                ("value", str(job_application.job_seeker.pk), "[PK of job seeker]"),
            ],
        )
    ) == snapshot(name="choose-employee")
    response = client.post(
        choose_employee_url,
        {
            "choose-employee-employee": job_application.job_seeker.pk,
            f"company_{company.pk}_add_employee_record-current_step": "choose-employee",
        },
    )
    assertRedirects(response, choose_approval_url)

    # Force step 2 even if the user tries to skip it
    response = client.get(end_url)
    assertRedirects(response, choose_approval_url)

    # Check "choose-approval" step
    soup = parse_response_to_soup(client.get(choose_approval_url), selector="#main .s-section")
    assert soup.find(id="id_choose-approval-approval").option["value"] == str(approval.pk)
    soup.find(id="id_choose-approval-approval").option["value"] = "[PK of Approval]"
    [input] = soup.select(selector=f"#id_company_{company.pk}_add_employee_record-current_step")
    input["name"] = input["name"].replace(str(company.pk), "[PK of Company]")
    input["id"] = input["id"].replace(str(company.pk), "[PK of Company]")
    assert str(soup) == snapshot(name="choose-approval")

    # ERROR : Submit data for the "choose-approval" step when the employee already has an employee record
    # typically if two members of the company want to create the record at the same time
    employee_record = EmployeeRecordFactory(job_application=job_application, status=Status.NEW)
    post_data = {
        "choose-approval-approval": job_application.approval.pk,
        f"company_{company.pk}_add_employee_record-current_step": "choose-approval",
    }
    # FIXME: improve this when we stop using formtools.Wizard
    with pytest.raises(TypeError):
        response = client.post(choose_approval_url, post_data)
    employee_record.delete()

    # Submit data for the "choose-approval" step
    response = client.post(choose_approval_url, post_data)
    assertRedirects(response, end_url, fetch_redirect_response=False)

    # get end_url to clear the wizard data
    client.get(end_url, follow=True)

    # Don't crash when going back to last step
    response = client.get(choose_approval_url)
    assertRedirects(response, choose_employee_url)

    response = client.get(end_url)
    assertRedirects(response, choose_employee_url)


def test_employee_list(client):
    company = CompanyFactory(with_membership=True)
    job_application_1 = JobApplicationFactory(to_company=company, with_approval=True)
    # Another one with the same job seeker to ensure we don't have duplicates
    JobApplicationFactory(
        to_company=company,
        job_seeker=job_application_1.job_seeker,
        with_approval=True,
        approval=job_application_1.approval,
    )
    # Hiring is older, the job seeker will be after job_application_1's one
    job_application_2 = JobApplicationFactory(
        to_company=company,
        with_approval=True,
        hiring_start_at=job_application_1.hiring_start_at - relativedelta(days=1),
    )
    # Has an employee record : we won't display it
    job_application_3 = JobApplicationFactory(to_company=company, with_approval=True)
    EmployeeRecordFactory(job_application=job_application_3, status=Status.NEW)

    client.force_login(company.members.first())

    choose_employee_url = reverse("employee_record_views:add", kwargs={"step": "choose-employee"})
    response = client.get(choose_employee_url)
    assert response.context["form"].fields["employee"].choices == [
        (None, "Sélectionnez le salarié"),
        (job_application_1.job_seeker.pk, job_application_1.job_seeker.get_full_name()),
        (job_application_2.job_seeker.pk, job_application_2.job_seeker.get_full_name()),
    ]


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
        {
            "choose-employee-employee": job_application.job_seeker.pk,
            f"company_{company.pk}_add_employee_record-current_step": "choose-employee",
        },
    )
    response = client.post(
        choose_approval_url,
        {
            "choose-approval-approval": job_application.approval.pk,
            f"company_{company.pk}_add_employee_record-current_step": "choose-approval",
        },
        follow=True,  # Don't stop to the `done` step
    )

    assertRedirects(response, end_url)


def test_choose_employee_step_with_a_bad_choice(client):
    company = CompanyFactory(with_membership=True)
    job_application = JobApplicationFactory(
        to_company=company,
        to_company__use_employee_record=True,
        with_approval=True,
    )
    EmployeeRecordFactory(job_application=job_application, status=Status.NEW)

    client.force_login(company.members.first())

    choose_employee_url = reverse("employee_record_views:add", kwargs={"step": "choose-employee"})

    response = client.post(
        choose_employee_url,
        {
            "choose-employee-employee": job_application.job_seeker.pk,
            f"company_{company.pk}_add_employee_record-current_step": "choose-employee",
        },
    )
    assert response.status_code == 200
    assert response.context["form"].errors == {
        "employee": [f"Sélectionnez un choix valide. {job_application.job_seeker.pk} n’en fait pas partie."]
    }
