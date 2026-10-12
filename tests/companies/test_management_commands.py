import datetime

from django.core import management
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertQuerySetEqual

from itou.companies.enums import CompanyKind, JobSource
from itou.companies.models import Company, JobDescription
from tests.cities.factories import create_city_guerande
from tests.companies import factories as companies_factories
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.utils.testing import remove_greetings


def test_update_companies_job_app_score(caplog):
    company_1 = companies_factories.CompanyFactory()
    company_2 = JobApplicationFactory(sent_by_prescriber_alone=True, to_company__with_jobs=True).to_company

    assert company_1.job_app_score == Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_2.job_app_score == Company.MAX_DEFAULT_JOB_APP_SCORE

    # Dry run first
    management.call_command("update_companies_job_app_score", wet_run=False)
    assert caplog.messages[0] == "Command launched with wet_run=False"
    assert caplog.messages[1] == "Updated 2 companies"

    company_1.refresh_from_db()
    company_2.refresh_from_db()

    assert company_1.job_app_score == Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_2.job_app_score == Company.MAX_DEFAULT_JOB_APP_SCORE

    caplog.clear()

    # Wet run now
    management.call_command("update_companies_job_app_score", wet_run=True)
    assert caplog.messages[0] == "Updated 2 companies"

    company_1.refresh_from_db()
    company_2.refresh_from_db()

    assert company_1.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_1.job_app_score == company_1.job_applications_received.count()
    assert company_2.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_2.spontaneous_applications_open_since is not None
    assert company_2.job_app_score == company_2.job_applications_received.count() / (
        company_2.job_description_through.count() + 1
    )

    # Deleting job descriptions should bring score back to job_applications_received.count().
    for jd in company_2.job_description_through.all():
        jd.delete()
    caplog.clear()
    management.call_command("update_companies_job_app_score", wet_run=True)
    # company_2 changed
    assert caplog.messages[0] == "Updated 1 companies"

    company_1.refresh_from_db()
    company_2.refresh_from_db()

    assert company_1.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_1.job_app_score == company_1.job_applications_received.count()
    assert company_2.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_2.job_app_score == company_2.job_applications_received.count()


@freeze_time("2023-05-01")
def test_update_companies_coords(settings, capsys, respx_mock):
    company_1 = companies_factories.CompanyFactory(
        coords="POINT (2.387311 48.917735)", geocoding_score=0.65
    )  # score too low
    company_2 = companies_factories.CompanyFactory(coords=None, geocoding_score=0.9)  # no coords
    company_3 = companies_factories.CompanyFactory(
        coords="POINT (5.43567 12.123876)", geocoding_score=0.76
    )  # score too low
    companies_factories.CompanyFactory(coords="POINT (5.43567 12.123876)", geocoding_score=0.9)

    settings.API_GEOPF_BASE_URL = "https://geo.foo"
    respx_mock.post("https://geo.foo/geocodage/search/csv/").respond(
        200,
        text=(
            "id;result_label;result_score;latitude;longitude\n"
            "42;7 rue de Laroche;0.77;42.42;13.13\n"  # score is lower than the minimum fiability score
            "12;5 rue Bigot;0.32;42.42;13.13\n"  # score is lower than the current one
            "78;9 avenue Delorme 92220 Boulogne;0.83;42.42;13.13\n"  # score is higher than current one
        ),
    )

    management.call_command("update_companies_coords", wet_run=True, verbosity=2)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "> about to geolocate count=3 objects without geolocation or with a low score.",
        "> count=3 of these have an address and a post code.",
        "API result score=0.77 label='7 rue de Laroche' "
        f"searched_address='{company_1.address_line_1} {company_1.post_code}' object_pk={company_1.pk}",
        "API result score=0.32 label='5 rue Bigot' "
        f"searched_address='{company_2.address_line_1} {company_2.post_code}' object_pk={company_2.pk}",
        "API result score=0.83 label='9 avenue Delorme 92220 Boulogne' "
        f"searched_address='{company_3.address_line_1} {company_3.post_code}' object_pk={company_3.pk}",
        "> count=1 companies geolocated with a high score.",
    ]

    company_3.refresh_from_db()
    assert company_3.ban_api_resolved_address == "9 avenue Delorme 92220 Boulogne"
    assert company_3.geocoding_updated_at == datetime.datetime(2023, 5, 1, 0, 0, tzinfo=datetime.UTC)
    assert company_3.geocoding_score == 0.83
    assert company_3.coords.x == 13.13
    assert company_3.coords.y == 42.42


def test_deactivate_old_job_description(snapshot, mailoutbox, django_capture_on_commit_callbacks, caplog, settings):
    create_test_romes_and_appellations(("N1101",))
    old_job_description_1 = companies_factories.JobDescriptionFactory(
        last_employer_update_at=timezone.now() - settings.DEACTIVATION_DELAY,
        company__with_membership=True,
        company__for_snapshot=True,
        for_snapshot=True,
    )
    old_job_description_2 = companies_factories.JobDescriptionFactory(
        last_employer_update_at=None,
        company__with_membership=True,
        location=create_city_guerande(),
    )
    # Inactive memberships or users should not receive the mail
    companies_factories.CompanyMembershipFactory(
        company=old_job_description_2.company, is_admin=False, is_active=False
    )
    companies_factories.CompanyMembershipFactory(
        company=old_job_description_2.company, is_admin=False, user__is_active=False
    )
    ft_job_description = companies_factories.JobDescriptionFactory(
        last_employer_update_at=None,
        location=None,
        source_kind=JobSource.PE_API,
    )
    recently_updated_job_description = companies_factories.JobDescriptionFactory(
        last_employer_update_at=timezone.now() - settings.DEACTIVATION_DELAY + datetime.timedelta(days=1),
        location=None,
    )
    assert JobDescription.objects.active().count() == 4
    with assertSnapshotQueries(snapshot(name="SQL")):
        with django_capture_on_commit_callbacks(execute=True):
            management.call_command("deactivate_old_job_descriptions")
    assertQuerySetEqual(
        JobDescription.objects.active(),
        [recently_updated_job_description, ft_job_description],
        ordered=False,
    )

    assert caplog.messages[:-1] == ["Deactivated 2 JobDescriptions"]
    assert len(mailoutbox) == 2

    assert set(sum((mail.to for mail in mailoutbox), [])) == set(
        old_job_description_1.company.memberships.values_list("user__email", flat=True)
        | old_job_description_2.company.memberships.values_list("user__email", flat=True)
    )
    mail = next(mail for mail in mailoutbox if mail.to == [old_job_description_1.company.members.get().email])
    assert mail.subject == snapshot(name="email subject")
    assert mail.body == snapshot(name="email body")


def test_deactivate_old_job_description_batch_size(mocker, caplog, settings):
    create_test_romes_and_appellations(("N1101",))
    companies_factories.JobDescriptionFactory.create_batch(
        3, last_employer_update_at=timezone.now() - settings.DEACTIVATION_DELAY
    )
    assert JobDescription.objects.active().count() == 3
    mocker.patch("itou.companies.management.commands.deactivate_old_job_descriptions.BATCH_SIZE", 1)

    management.call_command("deactivate_old_job_descriptions")
    assert JobDescription.objects.active().count() == 2
    assert [record.message for record in caplog.records if record.levelname == "ERROR"] == [
        "Too many old JobDescriptions to deactivate: 2"
    ]

    caplog.clear()
    management.call_command("deactivate_old_job_descriptions")
    assert JobDescription.objects.active().count() == 1
    assert [record.message for record in caplog.records if record.levelname == "ERROR"] == []


def test_deactivate_spontaneous_jobapps(snapshot, mailoutbox, django_capture_on_commit_callbacks, caplog, settings):
    company = companies_factories.CompanyWith2MembershipsFactory(
        name="Black Mesa",
        kind=CompanyKind.EI,
        spontaneous_applications_open_since=timezone.now() - settings.DEACTIVATION_DELAY,
    )
    # Inactive memberships or users should not receive the mail
    companies_factories.CompanyMembershipFactory(company=company, is_admin=False, is_active=False)
    companies_factories.CompanyMembershipFactory(company=company, is_admin=False, user__is_active=False)

    with assertSnapshotQueries(snapshot(name="SQL")):
        with django_capture_on_commit_callbacks(execute=True):
            management.call_command("deactivate_spontaneous_jobapps")

    company.refresh_from_db()
    assert company.spontaneous_applications_open_since is None
    assert not company.is_open_to_spontaneous_applications

    assert caplog.messages[:-1] == ["Deactivated spontaneous job applications for 1 Companies"]
    assert len(mailoutbox) == 2

    assert set(sum((mail.to for mail in mailoutbox), [])) == set(
        company.memberships.values_list("user__email", flat=True)
    )
    mail = next(mail for mail in mailoutbox if mail.to == [company.members.first().email])
    assert mail.subject == snapshot(name="email subject")
    assert remove_greetings(mail.body) == snapshot(name="email body")


def test_deactivate_spontaneous_jobapps_batch_size(mocker, caplog, settings):
    companies_factories.CompanyMembershipFactory.create_batch(
        3,
        company__spontaneous_applications_open_since=timezone.now() - settings.DEACTIVATION_DELAY,
    )
    assert Company.objects.filter(spontaneous_applications_open_since__isnull=False).count() == 3
    mocker.patch("itou.companies.management.commands.deactivate_spontaneous_jobapps.BATCH_SIZE", 1)

    management.call_command("deactivate_spontaneous_jobapps")
    assert Company.objects.filter(spontaneous_applications_open_since__isnull=False).count() == 2
    assert [record.message for record in caplog.records if record.levelname == "ERROR"] == [
        "Too many Companies to deactivate spontaneous job applications for: 2",
    ]

    caplog.clear()
    management.call_command("deactivate_spontaneous_jobapps")
    assert Company.objects.filter(spontaneous_applications_open_since__isnull=False).count() == 1
    assert [record.message for record in caplog.records if record.levelname == "ERROR"] == []
