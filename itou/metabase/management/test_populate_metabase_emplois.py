import datetime

import pytest
from django.contrib.gis.geos import Point
from django.core import management
from django.db import connection
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.analytics.factories import DatumFactory, StatsDashboardVisitFactory
from itou.approvals.enums import Origin
from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.eligibility.models import AdministrativeCriteria
from itou.geo.factories import QPVFactory
from itou.geo.utils import coords_to_geometry
from itou.institutions.factories import InstitutionFactory
from itou.job_applications.factories import JobApplicationFactory
from itou.metabase.tables.utils import hash_content
from itou.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from itou.siaes.factories import SiaeFactory
from itou.users.enums import IdentityProvider
from itou.users.factories import JobSeekerFactory, PrescriberFactory, SiaeStaffFactory


@freeze_time("2023-03-10")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_analytics():
    date_maj = datetime.date.today() + datetime.timedelta(days=-1)
    data0 = DatumFactory(code="ER-101", bucket="2021-12-31")
    data1 = DatumFactory(code="ER-102", bucket="2020-10-17")
    data2 = DatumFactory(code="ER-102-3436", bucket="2022-08-16")

    stats1 = StatsDashboardVisitFactory()
    stats2 = StatsDashboardVisitFactory()

    management.call_command("populate_metabase_emplois", mode="analytics")
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_analytics_v0 ORDER BY date")
        rows = cursor.fetchall()
        assert rows == [
            (
                str(data1.pk),
                "ER-102",
                datetime.date(2020, 10, 17),
                data1.value,
                "FS avec une erreur au premier retour",
                date_maj,
            ),
            (
                str(data0.pk),
                "ER-101",
                datetime.date(2021, 12, 31),
                data0.value,
                "FS intégrées (0000) au premier retour",
                date_maj,
            ),
            (
                str(data2.pk),
                "ER-102-3436",
                datetime.date(2022, 8, 16),
                data2.value,
                "FS avec une erreur 3436 au premier retour",
                date_maj,
            ),
        ]

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_private_dashboard_visits_v0 ORDER BY measured_at")
        rows = cursor.fetchall()
        assert rows == [
            (
                str(stats1.pk),
                datetime.datetime(2023, 3, 10),
                str(stats1.dashboard_id),
                stats1.department,
                stats1.region,
                str(stats1.current_siae_id),
                str(stats1.current_prescriber_organization_id),
                str(stats1.current_institution_id),
                stats1.user_kind,
                str(stats1.user_id),
                date_maj,
            ),
            (
                str(stats2.pk),
                datetime.datetime(2023, 3, 10),
                str(stats2.dashboard_id),
                stats2.department,
                stats2.region,
                str(stats2.current_siae_id),
                str(stats2.current_prescriber_organization_id),
                str(stats2.current_institution_id),
                stats2.user_kind,
                str(stats2.user_id),
                date_maj,
            ),
        ]


# We can use fakegun because datetime.date return FakeDate objects, but the database
# return datetime.date objects that are not equal...
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_job_seekers():
    QPVFactory(code="QP075019")

    # Importing this file makes a query so we need to do it inside a test
    # and before the assertNumQueries
    from itou.metabase.tables.job_seekers import get_user_age_in_years

    # First user
    #  - no job application
    #  - created by prescriber
    #  - no coords for QPV
    #  - uses PE_CONNECT
    #  - has no PE number
    #  - logged_in recently
    #  - in QPV
    user_1 = JobSeekerFactory(
        pk=2010,
        created_by=PrescriberFactory(),
        identity_provider=IdentityProvider.PE_CONNECT,
        pole_emploi_id="",
        last_login=timezone.now(),
        nir="179038704133768",
        post_code="33360",
        geocoding_score=1,
        coords=coords_to_geometry("48.85592", "2.41299"),
    )
    # Second user
    #  - job_application / approval from ai stock
    #  - created by siae staff
    #  - outside QPV
    user_2 = JobSeekerFactory(
        pk=15752,
        created_by=SiaeStaffFactory(),
        nir="271049232724647",
        geocoding_score=1,
        coords=Point(0, 0),  # QPV utils is mocked
    )
    job_application_2 = JobApplicationFactory(
        with_approval=True,
        job_seeker=user_2,
        approval__origin=Origin.AI_STOCK,
    )

    job_application_2.eligibility_diagnosis.administrative_criteria.add(*list(AdministrativeCriteria.objects.all()))

    # Third user
    #  - multiple eligibility diagnosis
    #  - last eligibility diagnosis from siae staff
    #  - not an AI
    user_3 = JobSeekerFactory(
        pk=26587,
        nir="297016314515713",
    )
    job_application_3 = JobApplicationFactory(
        job_seeker=user_3,
        created_at=datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc),
        with_approval=True,
        eligibility_diagnosis__author_kind="siae_staff",
        eligibility_diagnosis__author_prescriber_organization=None,
        eligibility_diagnosis__author_siae=SiaeFactory(),
        to_siae__kind="ETTI",
    )
    # Older accepted job_application with no eligibility diagnosis
    # Allow to check get_hiring_siae()
    JobApplicationFactory(
        job_seeker=user_3,
        with_approval=True,
        approval=job_application_3.approval,
        eligibility_diagnosis=None,
        created_at=datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
    )

    EligibilityDiagnosisFactory(
        job_seeker=user_3,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc),
    )

    num_queries = 1  # Get administrative criteria
    num_queries += 1  # Count rows
    num_queries += 1  # Select all elements ids (chunked_queryset)
    num_queries += 1  # Select last pk for current chunck
    num_queries += 1  # Select job seekers chunck (with annotations)
    num_queries += 1  # Prefetch EligibilityDiagnosis with anotations, author_prescriber_organization and author_siae
    num_queries += 1  # Prefetch JobApplications with Siaes
    num_queries += 1  # Prefetch created_by Users
    num_queries += 1  # Get QPV users
    num_queries += 1  # Select AI stock approvals pks
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="job_seekers")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM candidats ORDER BY id")
        rows = cursor.fetchall()

    assert rows == [
        (
            2010,
            "7ee747dfcdd882876c5ca6759dca3f927618bd6192e0be2fd9e5e122435d881a",
            "28e41a0abf44151d54b9006aa6308d71d15284f7cc83a200b8fc6a9ffdf58352",
            "Homme",
            79,
            3,
            get_user_age_in_years(user_1),
            datetime.date.today(),
            "par prescripteur",
            1,
            0,
            datetime.date.today(),
            1,
            "33360",
            "33",
            "33 - Gironde",
            "Nouvelle-Aquitaine",
            "Adresse en QPV",
            0,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
            datetime.date.today() - datetime.timedelta(days=1),
        ),
        (
            15752,
            "60cddb9b00716b793cc5ebc61500e796722e486a169c3d2c9dde3026c13a8412",
            "d4d74522c83e8371e4ccafa994a70bb802b59d8e143177cf048e71c9b9d2e34a",
            "Femme",
            71,
            4,
            get_user_age_in_years(user_2),
            datetime.date.today(),
            "par employeur",
            0,
            1,
            None,
            0,
            "",
            "",
            None,
            None,
            "Adresse hors QPV",
            1,
            1,
            1,
            job_application_2.eligibility_diagnosis.created_at.date(),
            job_application_2.eligibility_diagnosis.author_prescriber_organization.id,
            None,
            "Prescripteur",
            "Prescripteur PE",
            job_application_2.eligibility_diagnosis.author_prescriber_organization.display_name,
            "EI",
            4,
            14,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            datetime.date.today() - datetime.timedelta(days=1),
        ),
        (
            26587,
            "70898ff70d3b980b644ed25a0e1c93bd92f8f93ba9e27e2580bd970a1dc12bb4",
            "2eb53772722d3026b539173c62ba7adc1756e5ab1f03b95ce4026c27d177bd34",
            "Femme",
            97,
            1,
            get_user_age_in_years(user_3),
            datetime.date.today(),
            "autonome",
            0,
            1,
            None,
            0,
            "",
            "",
            None,
            None,
            "Adresse non-géolocalisée",
            2,
            2,
            2,
            job_application_3.eligibility_diagnosis.created_at.date(),
            None,
            job_application_3.eligibility_diagnosis.author_siae.id,
            "Employeur",
            "Employeur EI",
            job_application_3.eligibility_diagnosis.author_siae.display_name,
            "ETTI",
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            datetime.date.today() - datetime.timedelta(days=1),
        ),
    ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_criteria():
    num_queries = 1  # Count criteria
    num_queries += 1  # Select criteria IDs
    num_queries += 1  # Select one chunk of criteria IDs
    num_queries += 1  # Select criteria with columns
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="criteria")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM critères_iae ORDER BY id")
        rows = cursor.fetchall()
        assert len(rows) == 18
        assert rows[0] == (1, "Bénéficiaire du RSA", "1", "Revenu de solidarité active", datetime.date(2023, 2, 1))


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_approvals():
    approval = ApprovalFactory()
    pe_approval = PoleEmploiApprovalFactory()

    num_queries = 1  # Count approvals
    num_queries += 1  # Count PE approvals
    num_queries += 1  # Select approval IDs
    num_queries += 1  # Select approvals IDs, chunk by 1000
    num_queries += 1  # Select approvals with columns
    num_queries += 1  # Prefetch users
    num_queries += 1  # Prefetch JobApplications

    num_queries += 1  # Select PE approval IDs
    num_queries += 1  # Select PE approvals IDs, chunk by 1000
    num_queries += 1  # Select PE approvals with columns
    num_queries += 1  # Select prescriber organizations
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="approvals")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM pass_agréments ORDER BY date_début")
        rows = cursor.fetchall()
        assert rows == [
            (
                "PASS IAE (XXXXX)",
                datetime.date(2023, 2, 2),
                datetime.date(2025, 2, 1),
                datetime.timedelta(days=730),
                approval.user.id,
                hash_content(approval.user_id),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                0,
                hash_content(approval.number),
                datetime.date(2023, 2, 1),
            ),
            (
                "Agrément PE",
                datetime.date(2023, 2, 2),
                datetime.date(2025, 2, 1),
                datetime.timedelta(days=730),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                0,
                hash_content(pe_approval.number),
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_institutions():
    institution = InstitutionFactory(department="14")

    num_queries = 1  # Count institutions
    num_queries += 1  # Select institution IDs
    num_queries += 1  # Select one chunk of institution IDs
    num_queries += 1  # Select institutions with columns
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="institutions")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM institutions ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                institution.id,
                institution.kind,
                "14",
                "14 - Calvados",
                "Normandie",
                institution.name,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_evaluation_campaigns():
    evaluation_campaign = EvaluationCampaignFactory()

    num_queries = 1  # Count campaigns
    num_queries += 1  # Select campaign IDs
    num_queries += 1  # Select one chunk of campaign IDs
    num_queries += 1  # Select campaigns with columns
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="evaluation_campaigns")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM cap_campagnes ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                evaluation_campaign.id,
                evaluation_campaign.name,
                evaluation_campaign.institution_id,
                evaluation_campaign.evaluated_period_start_at,
                evaluation_campaign.evaluated_period_end_at,
                evaluation_campaign.chosen_percent,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_evaluated_siaes():
    evaluated_siae = EvaluatedSiaeFactory()

    num_queries = 1  # Count evaluated siaes
    num_queries += 1  # Select evaluated siae IDs
    num_queries += 1  # Select one chunk of evaluated siae IDs
    num_queries += 1  # Select evaluated siaes with columns
    num_queries += 1  # Select related evaluated job applications
    num_queries += 1  # Select related campaigns
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="evaluated_siaes")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM cap_structures ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                evaluated_siae.id,
                evaluated_siae.evaluation_campaign_id,
                evaluated_siae.siae_id,
                evaluated_siae.state,
                evaluated_siae.reviewed_at,
                evaluated_siae.final_reviewed_at,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_evaluated_job_applications():
    evaluated_job_application = EvaluatedJobApplicationFactory()

    num_queries = 1  # Count evaluated job applications
    num_queries += 1  # Select evaluated job application IDs
    num_queries += 1  # Select one chunk of evaluated job application IDs
    num_queries += 1  # Select evaluated job applications with columns
    num_queries += 1  # Select related evaluated siaes
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="evaluated_job_applications")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM cap_candidatures ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                evaluated_job_application.id,
                str(evaluated_job_application.job_application_id),
                evaluated_job_application.evaluated_siae_id,
                evaluated_job_application.compute_state(),
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_evaluated_criteria():
    evaluated_job_application = EvaluatedJobApplicationFactory()
    evaluated_criteria = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application)

    num_queries = 1  # Count evaluated criteria
    num_queries += 1  # Select evaluated criteria IDs
    num_queries += 1  # Select one chunk of evaluated criteria IDs
    num_queries += 1  # Select evaluated criteria with columns
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="evaluated_criteria")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM cap_critères_iae ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                evaluated_criteria.id,
                evaluated_criteria.administrative_criteria_id,
                evaluated_criteria.evaluated_job_application_id,
                evaluated_criteria.uploaded_at,
                evaluated_criteria.submitted_at,
                evaluated_criteria.review_state,
                datetime.date(2023, 2, 1),
            ),
        ]


def test_data_inconsistencies(capsys):
    approval = ApprovalFactory()

    with assertNumQueries(1):  # Select the job seekers
        management.call_command("populate_metabase_emplois", mode="data_inconsistencies")

    stdout, _ = capsys.readouterr()
    out_lines = stdout.splitlines()
    assert out_lines[0] == "Checking data for inconsistencies."
    assert "timeit: method=report_data_inconsistencies completed in seconds=" in out_lines[1]
    assert "timeit: method=handle completed in seconds=" in out_lines[2]

    approval.user.kind = "siae_staff"
    approval.user.save()

    with pytest.raises(RuntimeError):
        management.call_command("populate_metabase_emplois", mode="data_inconsistencies")
    stdout, _ = capsys.readouterr()
    assert stdout.splitlines() == [
        "Checking data for inconsistencies.",
        "FATAL ERROR: At least one user has an approval but is not a job seeker",
    ]
