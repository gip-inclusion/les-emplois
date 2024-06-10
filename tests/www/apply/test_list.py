import datetime

from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.eligibility.models import AdministrativeCriteria
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.www.apply.forms import CompanyFilterJobApplicationsForm
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import parse_response_to_soup


@freeze_time("2023-04-13")
def test_list_warns_about_long_awaiting_applications(client, snapshot):
    hit_pit = CompanyFactory(pk=42, name="Hit Pit", with_membership=True)

    now = timezone.now()
    org = PrescriberOrganizationWithMembershipFactory(
        membership__user__first_name="Max", membership__user__last_name="Throughput"
    )
    sender = org.active_members.get()
    job_seeker = JobSeekerFactory(first_name="Jacques", last_name="Henry")
    JobApplicationFactory(
        id="11111111-1111-1111-1111-111111111111",
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="Third application",
        created_at=now - relativedelta(weeks=2),
    )
    JobApplicationFactory(
        id="22222222-2222-2222-2222-222222222222",
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="Second application",
        created_at=now - relativedelta(weeks=3, days=5),
    )
    JobApplicationFactory(
        id="33333333-3333-3333-3333-333333333333",
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="First application",
        created_at=now - relativedelta(weeks=8),
    )

    client.force_login(hit_pit.members.get())
    response = client.get(reverse("apply:list_for_siae"))
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert str(results_section) == snapshot(name="SIAE - warnings for 2222 and 3333")

    client.force_login(sender)
    response = client.get(reverse("apply:list_prescriptions"))
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert str(results_section) == snapshot(name="PRESCRIBER - warnings for 2222 and 3333")

    client.force_login(job_seeker)
    response = client.get(reverse("apply:list_for_job_seeker"))
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert str(results_section) == snapshot(name="JOB SEEKER - no warnings")


def test_list_hidden_fields(client):
    """
    Sync the filter state across the two forms on the page with hidden fields.

    The list has two forms for filtering:
        1. the top bar .btn-filter-dropdown with quick filters, and
        2. the offcanvas form with all the filters.

    When users select filters from the top bar, the offcanvas form is reloaded
    with HTMX, keeping filters in sync.

    When users select filters from the offcanvas, the top form should include
    the active filters (as hidden), even though users cannot changes these
    fields from the top form.
    """
    # Companies subject to eligibility, with an application that has
    # `selected_jobs`, have access to all filters.
    company = CompanyFactory(
        subject_to_eligibility=True,
        with_membership=True,
        with_jobs=True,
    )
    jobs = company.job_description_through.all()

    job_seeker1 = JobSeekerFactory()
    prescriber_organization1 = PrescriberOrganizationWithMembershipFactory(authorized=True)
    sender1 = prescriber_organization1.active_members.get()
    criteria = AdministrativeCriteria.objects.filter(level=1).first()
    diag1 = IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker1,
        from_prescriber=True,
        author_prescriber_organization=prescriber_organization1,
        author=sender1,
    )
    diag1.administrative_criteria.add(criteria)
    JobApplicationFactory(
        to_company=company,
        job_seeker__department="03",
        eligibility_diagnosis=diag1,
        selected_jobs=company.job_description_through.all(),
    )
    job_seeker2 = JobSeekerFactory()
    prescriber_organization2 = PrescriberOrganizationWithMembershipFactory(authorized=True)
    sender2 = prescriber_organization2.active_members.get()
    diag2 = IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker2,
        from_prescriber=True,
        author_prescriber_organization=prescriber_organization2,
        author=sender2,
    )
    diag2.administrative_criteria.add(criteria)
    JobApplicationFactory(
        to_company=company,
        job_seeker__department="23",
        eligibility_diagnosis=diag2,
        selected_jobs=company.job_description_through.all(),
    )
    job_app = JobApplicationFactory(sent_by_another_employer=True, to_company=company, job_seeker__department="23")

    form = CompanyFilterJobApplicationsForm(JobApplication.objects.all(), company)
    known_filters = {
        "criteria",
        "departments",
        "eligibility_validated",
        "end_date",
        "job_seekers",
        "pass_iae_active",
        "pass_iae_suspended",
        "selected_jobs",
        "sender_companies",
        "sender_prescriber_organizations",
        "senders",
        "start_date",
        "states",
    }
    assert set(form.fields) == known_filters

    client.force_login(company.members.get())
    filters = {
        "criteria": criteria.pk,
        "eligibility_validated": "on",
        "end_date": datetime.date.max,
        "job_seekers": [job_seeker1.pk, job_seeker2.pk],
        "pass_iae_active": "on",
        "pass_iae_suspended": "on",
        "sender_companies": [job_app.sender_company.pk],
        "sender_prescriber_organizations": [prescriber_organization1.pk, prescriber_organization2.pk],
        "senders": [sender1.pk, sender2.pk],
        "start_date": datetime.date.min,
        # Accessible via top bar, should not be present as hidden.
        "departments": ["03", "23"],
        "selected_jobs": [j.pk for j in jobs],
        "states": [state.value for state in JobApplicationState],
    }
    response = client.get(reverse("apply:list_for_siae"), filters)

    top_filters = parse_response_to_soup(response, selector=".btn-dropdown-filter-group")
    remaining_filters = known_filters - set(form.top_bar_filters)
    hidden_fields = top_filters.find_all("input", attrs={"type": "hidden"})
    assert set(f["name"] for f in hidden_fields) == set(remaining_filters)
    expected_hiddens = {
        ("criteria", f"{criteria.pk}"),
        ("eligibility_validated", "True"),
        ("end_date", "9999-12-31"),
        ("pass_iae_active", "True"),
        ("pass_iae_suspended", "True"),
        ("sender_companies", f"{job_app.sender_company.pk}"),
        ("sender_prescriber_organizations", f"{prescriber_organization1.pk}"),
        ("sender_prescriber_organizations", f"{prescriber_organization2.pk}"),
        ("senders", f"{sender1.pk}"),
        ("senders", f"{sender2.pk}"),
        ("start_date", "0001-01-01"),
    }
    assert set((hidden["name"], hidden["value"]) for hidden in hidden_fields) == expected_hiddens

    offcanvas_form = parse_response_to_soup(response, selector="#offcanvasApplyFilters")
    hidden_fields = offcanvas_form.find_all("input", {"type": "hidden"})
    expected_hiddens = {
        ("job_seekers", f"{job_seeker1.pk}"),
        ("job_seekers", f"{job_seeker2.pk}"),
    }
    assert set((hidden["name"], hidden["value"]) for hidden in hidden_fields) == expected_hiddens
