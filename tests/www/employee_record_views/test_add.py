from dateutil.relativedelta import relativedelta
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.employee_record.enums import Status
from itou.utils.urls import add_url_params
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.test import KNOWN_SESSION_KEYS, assertSnapshotQueries, parse_response_to_soup


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
    reset_url = reverse("employee_record_views:list")

    # Start view
    # ----------------------------------------------------------------
    with assertSnapshotQueries(snapshot(name="start-queries")):
        response = client.get(add_url_params(reverse("employee_record_views:add"), {"reset_url": reset_url}))

    [wizard_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
    expected_session = {
        "config": {
            "session_kind": "add-employee-record",
            "reset_url": reset_url,
        },
    }
    assert client.session[wizard_session_name] == expected_session
    choose_employee_url = reverse(
        "employee_record_views:add", kwargs={"session_uuid": wizard_session_name, "step": "choose-employee"}
    )
    assertRedirects(response, choose_employee_url)

    # Choose employee step
    # ----------------------------------------------------------------
    with assertSnapshotQueries(snapshot(name="choose-employee-queries")):
        response = client.get(choose_employee_url)
    assert str(
        parse_response_to_soup(
            response,
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
    post_data = {
        "employee": str(job_application.job_seeker.pk),
    }
    response = client.post(choose_employee_url, post_data)
    expected_session["choose-employee"] = post_data
    assert client.session[wizard_session_name] == expected_session
    choose_approval_url = reverse(
        "employee_record_views:add", kwargs={"session_uuid": wizard_session_name, "step": "choose-approval"}
    )
    assertRedirects(response, choose_approval_url)

    # Choose approval step
    # ----------------------------------------------------------------
    with assertSnapshotQueries(snapshot(name="choose-approval-queries")):
        response = client.get(choose_approval_url)
    soup = parse_response_to_soup(
        response,
        selector="#main .s-section",
        replace_in_attr=[
            ("value", str(approval.pk), "[PK of Approval]"),
            ("value", wizard_session_name, "[UUID of session]"),
        ],
    )
    assert str(soup) == snapshot(name="choose-approval")

    # ERROR : Submit data for the "choose-approval" step when the employee already has an employee record
    # typically if two members of the company want to create the record at the same time
    employee_record = EmployeeRecordFactory(job_application=job_application, status=Status.NEW)
    post_data = {
        "approval": job_application.approval.pk,
    }
    response = client.post(choose_approval_url, post_data, follow=True)
    # We are redirected to choose employee step
    assertRedirects(response, choose_employee_url)
    assertContains(response, " Certaines informations sont absentes ou invalides")
    employee_record.delete()

    # Submit data for the "choose-approval" step
    response = client.post(choose_approval_url, post_data)
    next_url = reverse("employee_record_views:create", kwargs={"job_application_id": job_application.pk})
    assertRedirects(response, next_url, fetch_redirect_response=False)

    # The wizard is cleared
    assert wizard_session_name not in client.session

    # We cannot go back to last step
    response = client.get(choose_approval_url)
    # FIXME: redirect to reset url with a message ?
    assert response.status_code == 404


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

    reset_url = reverse("employee_record_views:list")
    response = client.get(add_url_params(reverse("employee_record_views:add"), {"reset_url": reset_url}))

    [wizard_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
    choose_employee_url = reverse(
        "employee_record_views:add", kwargs={"session_uuid": wizard_session_name, "step": "choose-employee"}
    )
    assertRedirects(response, choose_employee_url)

    response = client.get(choose_employee_url)
    assert response.context["form"].fields["employee"].choices == [
        (None, "Sélectionnez le salarié"),
        (job_application_1.job_seeker.pk, job_application_1.job_seeker.get_full_name()),
        (job_application_2.job_seeker.pk, job_application_2.job_seeker.get_full_name()),
    ]


def test_choose_employee_step_with_a_bad_choice(client):
    company = CompanyFactory(with_membership=True)
    job_application = JobApplicationFactory(
        to_company=company,
        to_company__use_employee_record=True,
        with_approval=True,
    )
    EmployeeRecordFactory(job_application=job_application, status=Status.NEW)

    client.force_login(company.members.first())

    reset_url = reverse("employee_record_views:list")
    response = client.get(add_url_params(reverse("employee_record_views:add"), {"reset_url": reset_url}))

    [wizard_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
    choose_employee_url = reverse(
        "employee_record_views:add", kwargs={"session_uuid": wizard_session_name, "step": "choose-employee"}
    )
    assertRedirects(response, choose_employee_url)

    response = client.post(choose_employee_url, {"employee": job_application.job_seeker.pk})
    assert response.status_code == 200
    assert response.context["form"].errors == {
        "employee": [f"Sélectionnez un choix valide. {job_application.job_seeker.pk} n’en fait pas partie."]
    }
