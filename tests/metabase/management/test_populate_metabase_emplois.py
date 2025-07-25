import datetime

import pytest
from django.contrib.gis.geos import Point
from django.core import management
from django.db import connection, transaction
from django.utils import timezone
from freezegun import freeze_time
from psycopg.types.range import Range
from pytest_django.asserts import assertNumQueries

from itou.approvals.enums import Origin
from itou.common_apps.address.departments import DEPARTMENTS
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import JobDescription
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.models import AdministrativeCriteria, SelectedAdministrativeCriteria
from itou.geo.utils import coords_to_geometry
from itou.job_applications.enums import JobApplicationState
from itou.metabase.tables import gps
from itou.metabase.tables.utils import hash_content
from itou.users.enums import IdentityProvider, UserKind
from itou.utils.db import dictfetchall
from itou.utils.types import InclusiveDateRange
from tests.analytics.factories import DatumFactory, StatsDashboardVisitFactory
from tests.approvals.factories import (
    ApprovalFactory,
    PoleEmploiApprovalFactory,
    ProlongationFactory,
    ProlongationRequestDenyInformationFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, JobDescriptionFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.geo.factories import QPVFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
)
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


@freeze_time("2023-03-10")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_analytics():
    date_maj = timezone.localdate() + datetime.timedelta(days=-1)
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
                "2020-10-17",
                data1.value,
                "FS avec une erreur au premier retour",
                date_maj,
            ),
            (
                str(data0.pk),
                "ER-101",
                "2021-12-31",
                data0.value,
                "FS intégrées (0000) au premier retour",
                date_maj,
            ),
            (
                str(data2.pk),
                "ER-102-3436",
                "2022-08-16",
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
                stats1.pk,
                datetime.datetime(2023, 3, 10, tzinfo=datetime.UTC),
                str(stats1.dashboard_id),
                stats1.department,
                stats1.region,
                stats1.current_company_id,
                stats1.current_prescriber_organization_id,
                stats1.current_institution_id,
                stats1.user_kind,
                stats1.user_id,
                date_maj,
            ),
            (
                stats2.pk,
                datetime.datetime(2023, 3, 10, tzinfo=datetime.UTC),
                str(stats2.dashboard_id),
                stats2.department,
                stats2.region,
                stats2.current_company_id,
                stats2.current_prescriber_organization_id,
                stats2.current_institution_id,
                stats2.user_kind,
                stats2.user_id,
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
        created_by=PrescriberFactory(),
        identity_provider=IdentityProvider.PE_CONNECT,
        jobseeker_profile__pole_emploi_id="",
        last_login=timezone.now(),
        first_login=timezone.now(),
        jobseeker_profile__nir="179038704133768",
        post_code="33360",
        geocoding_score=1,
        coords=coords_to_geometry("48.85592", "2.41299"),
    )
    # Second user
    #  - job_application / approval from ai stock
    #  - created by an employer
    #  - outside QPV
    #  - expired eligibility diagnosis
    user_2 = JobSeekerFactory(
        created_by=EmployerFactory(),
        jobseeker_profile__nir="271049232724647",
        geocoding_score=1,
        coords=Point(0, 0),  # QPV utils is mocked
        with_pole_emploi_id=True,
    )
    job_application_2 = JobApplicationFactory(
        with_approval=True,
        eligibility_diagnosis__expired=True,
        approval__eligibility_diagnosis=None,
        job_seeker=user_2,
        approval__origin=Origin.AI_STOCK,
    )

    job_application_2.eligibility_diagnosis.administrative_criteria.add(*list(AdministrativeCriteria.objects.all()))

    # Third user
    #  - multiple eligibility diagnosis
    #  - last eligibility diagnosis with a certified criteria from an employer
    #  - not an AI
    #  - outside QPV but missing geocoding score
    user_3 = JobSeekerFactory(
        jobseeker_profile__nir="297016314515713",
        with_pole_emploi_id=True,
        geocoding_score=None,
        coords=Point(0, 0),  # QPV utils is mocked
    )
    job_application_3 = JobApplicationFactory(
        job_seeker=user_3,
        created_at=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
        with_approval=True,
        eligibility_diagnosis__author_kind=UserKind.EMPLOYER,
        eligibility_diagnosis__author_prescriber_organization=None,
        eligibility_diagnosis__author_siae=CompanyFactory(),
        eligibility_diagnosis__certifiable=True,
        eligibility_diagnosis__criteria_kinds=[AdministrativeCriteriaKind.RSA],
        to_company__kind="ETTI",
    )
    user_3_selected_criteria = SelectedAdministrativeCriteria.objects.get(
        eligibility_diagnosis=job_application_3.eligibility_diagnosis
    )
    user_3_selected_criteria.certified = True
    user_3_selected_criteria.certified_at = timezone.now()
    user_3_selected_criteria.certification_period = InclusiveDateRange(
        datetime.date(2025, 3, 13),
        datetime.date(2025, 6, 13),
    )
    user_3_selected_criteria.save()
    # Older accepted job_application with no eligibility diagnosis
    # Allow to check get_hiring_company()
    JobApplicationFactory(
        job_seeker=user_3,
        with_approval=True,
        approval=job_application_3.approval,
        eligibility_diagnosis=None,
        created_at=datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC),
    )

    IAEEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker=user_3,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Get administrative criteria
    num_queries += 1  # Count rows
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select all elements ids (chunked_queryset)
    num_queries += 1  # Select last pk for current chunk
    num_queries += 1  # Select job seekers chunk (with annotations)
    num_queries += 1  # Prefetch EligibilityDiagnosis with annotations, author_prescriber_organization and author_siae
    num_queries += 1  # Prefetch EligibilityDiagnosis's selected administrative criteria
    num_queries += 1  # Prefetch JobApplications with Siaes
    num_queries += 1  # Get QPV users
    num_queries += 1  # Select AI stock approvals pks
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="job_seekers")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM candidats_v0 ORDER BY id")
        rows = dictfetchall(cursor)

    assert rows == [
        {
            "id": user_1.pk,
            "hash_nir": "28e41a0abf44151d54b9006aa6308d71d15284f7cc83a200b8fc6a9ffdf58352",
            "sexe_selon_nir": "Homme",
            "annee_naissance_selon_nir": 79,
            "mois_naissance_selon_nir": 3,
            "age": get_user_age_in_years(user_1),
            "date_inscription": timezone.localdate(),
            "type_inscription": "par prescripteur",
            "pe_connect": 1,
            "pe_inscrit": 0,
            "date_dernière_connexion": timezone.localdate(),
            "date_premiere_connexion": timezone.localdate(),
            "actif": 1,
            "code_postal": "33360",
            "département": "33",
            "nom_département": "33 - Gironde",
            "région": "Nouvelle-Aquitaine",
            "adresse_en_qpv": "Adresse en QPV",
            "total_candidatures": 0,
            "total_embauches": 0,
            "total_diagnostics": 0,
            "date_diagnostic": None,
            "date_expiration_diagnostic": None,
            "diagnostic_valide": None,
            "id_auteur_diagnostic_prescripteur": None,
            "id_auteur_diagnostic_employeur": None,
            "type_auteur_diagnostic": None,
            "sous_type_auteur_diagnostic": None,
            "nom_auteur_diagnostic": None,
            "type_structure_dernière_embauche": None,
            "total_critères_niveau_1": None,
            "total_critères_niveau_2": None,
            "critère_n1_bénéficiaire_du_rsa": None,
            "critère_n1_bénéficiaire_du_rsa_certifié": None,
            "critère_n1_bénéficiaire_du_rsa_date_certification": None,
            "critère_n1_bénéficiaire_du_rsa_période_certification": None,
            "critère_n1_allocataire_ass": None,
            "critère_n1_allocataire_aah": None,
            "critère_n1_allocataire_aah_certifié": None,
            "critère_n1_allocataire_aah_date_certification": None,
            "critère_n1_allocataire_aah_période_certification": None,
            "critère_n1_detld_plus_de_24_mois": None,
            "critère_n2_niveau_d_étude_3_cap_bep_ou_infra": None,
            "critère_n2_senior_plus_de_50_ans": None,
            "critère_n2_jeune_moins_de_26_ans": None,
            "critère_n2_sortant_de_l_ase": None,
            "critère_n2_deld_12_à_24_mois": None,
            "critère_n2_travailleur_handicapé": None,
            "critère_n2_parent_isolé": None,
            "critère_n2_parent_isolé_certifié": None,
            "critère_n2_parent_isolé_date_certification": None,
            "critère_n2_parent_isolé_période_certification": None,
            "critère_n2_personne_sans_hébergement_ou_hébergée_ou_ayant_u": None,
            "critère_n2_réfugié_statutaire_bénéficiaire_d_une_protectio": None,
            "critère_n2_résident_zrr": None,
            "critère_n2_résident_qpv": None,
            "critère_n2_sortant_de_détention_ou_personne_placée_sous_main": None,
            "critère_n2_maîtrise_de_la_langue_française": None,
            "critère_n2_mobilité": None,
            "injection_ai": 0,
            "date_mise_à_jour_metabase": timezone.localdate() - datetime.timedelta(days=1),
        },
        {
            "id": user_2.pk,
            "hash_nir": "d4d74522c83e8371e4ccafa994a70bb802b59d8e143177cf048e71c9b9d2e34a",
            "sexe_selon_nir": "Femme",
            "annee_naissance_selon_nir": 71,
            "mois_naissance_selon_nir": 4,
            "age": get_user_age_in_years(user_2),
            "date_inscription": timezone.localdate(),
            "type_inscription": "par employeur",
            "pe_connect": 0,
            "pe_inscrit": 1,
            "date_dernière_connexion": None,
            "date_premiere_connexion": None,
            "actif": 0,
            "code_postal": "",
            "département": "",
            "nom_département": None,
            "région": None,
            "adresse_en_qpv": "Adresse hors QPV",
            "total_candidatures": 1,
            "total_embauches": 1,
            "total_diagnostics": 1,
            "date_diagnostic": job_application_2.eligibility_diagnosis.created_at.date(),
            "date_expiration_diagnostic": job_application_2.eligibility_diagnosis.expires_at,
            "diagnostic_valide": 0,
            "id_auteur_diagnostic_prescripteur": job_application_2.eligibility_diagnosis.author_prescriber_organization.id,  # noqa: E501
            "id_auteur_diagnostic_employeur": None,
            "type_auteur_diagnostic": "Prescripteur",
            "sous_type_auteur_diagnostic": "Prescripteur FT",
            "nom_auteur_diagnostic": job_application_2.eligibility_diagnosis.author_prescriber_organization.display_name,  # noqa: E501
            "type_structure_dernière_embauche": "EI",
            "total_critères_niveau_1": 4,
            "total_critères_niveau_2": 14,
            "critère_n1_bénéficiaire_du_rsa": 1,
            "critère_n1_bénéficiaire_du_rsa_certifié": None,
            "critère_n1_bénéficiaire_du_rsa_date_certification": None,
            "critère_n1_bénéficiaire_du_rsa_période_certification": None,
            "critère_n1_allocataire_ass": 1,
            "critère_n1_allocataire_aah": 1,
            "critère_n1_allocataire_aah_certifié": None,
            "critère_n1_allocataire_aah_date_certification": None,
            "critère_n1_allocataire_aah_période_certification": None,
            "critère_n1_detld_plus_de_24_mois": 1,
            "critère_n2_niveau_d_étude_3_cap_bep_ou_infra": 1,
            "critère_n2_senior_plus_de_50_ans": 1,
            "critère_n2_jeune_moins_de_26_ans": 1,
            "critère_n2_sortant_de_l_ase": 1,
            "critère_n2_deld_12_à_24_mois": 1,
            "critère_n2_travailleur_handicapé": 1,
            "critère_n2_parent_isolé": 1,
            "critère_n2_parent_isolé_certifié": None,
            "critère_n2_parent_isolé_date_certification": None,
            "critère_n2_parent_isolé_période_certification": None,
            "critère_n2_personne_sans_hébergement_ou_hébergée_ou_ayant_u": 1,
            "critère_n2_réfugié_statutaire_bénéficiaire_d_une_protectio": 1,
            "critère_n2_résident_zrr": 1,
            "critère_n2_résident_qpv": 1,
            "critère_n2_sortant_de_détention_ou_personne_placée_sous_main": 1,
            "critère_n2_maîtrise_de_la_langue_française": 1,
            "critère_n2_mobilité": 1,
            "injection_ai": 1,
            "date_mise_à_jour_metabase": timezone.localdate() - datetime.timedelta(days=1),
        },
        {
            "id": user_3.pk,
            "hash_nir": "2eb53772722d3026b539173c62ba7adc1756e5ab1f03b95ce4026c27d177bd34",
            "sexe_selon_nir": "Femme",
            "annee_naissance_selon_nir": 97,
            "mois_naissance_selon_nir": 1,
            "age": get_user_age_in_years(user_3),
            "date_inscription": timezone.localdate(),
            "type_inscription": "autonome",
            "pe_connect": 0,
            "pe_inscrit": 1,
            "date_dernière_connexion": None,
            "date_premiere_connexion": None,
            "actif": 0,
            "code_postal": "",
            "département": "",
            "nom_département": None,
            "région": None,
            "adresse_en_qpv": "Adresse hors QPV",
            "total_candidatures": 2,
            "total_embauches": 2,
            "total_diagnostics": 2,
            "date_diagnostic": job_application_3.eligibility_diagnosis.created_at.date(),
            "date_expiration_diagnostic": job_application_3.eligibility_diagnosis.expires_at,
            "diagnostic_valide": 1,
            "id_auteur_diagnostic_prescripteur": None,
            "id_auteur_diagnostic_employeur": job_application_3.eligibility_diagnosis.author_siae.id,
            "type_auteur_diagnostic": "Employeur",
            "sous_type_auteur_diagnostic": "Employeur EI",
            "nom_auteur_diagnostic": job_application_3.eligibility_diagnosis.author_siae.display_name,
            "type_structure_dernière_embauche": "ETTI",
            "total_critères_niveau_1": 1,
            "total_critères_niveau_2": 0,
            "critère_n1_bénéficiaire_du_rsa": 1,
            "critère_n1_bénéficiaire_du_rsa_certifié": 1,
            "critère_n1_bénéficiaire_du_rsa_date_certification": user_3_selected_criteria.certified_at,
            "critère_n1_bénéficiaire_du_rsa_période_certification": Range(
                datetime.date(2025, 3, 13), datetime.date(2025, 6, 14), "[)"
            ),
            "critère_n1_allocataire_ass": 0,
            "critère_n1_allocataire_aah": 0,
            "critère_n1_allocataire_aah_certifié": None,
            "critère_n1_allocataire_aah_date_certification": None,
            "critère_n1_allocataire_aah_période_certification": None,
            "critère_n1_detld_plus_de_24_mois": 0,
            "critère_n2_niveau_d_étude_3_cap_bep_ou_infra": 0,
            "critère_n2_senior_plus_de_50_ans": 0,
            "critère_n2_jeune_moins_de_26_ans": 0,
            "critère_n2_sortant_de_l_ase": 0,
            "critère_n2_deld_12_à_24_mois": 0,
            "critère_n2_travailleur_handicapé": 0,
            "critère_n2_parent_isolé": 0,
            "critère_n2_parent_isolé_certifié": None,
            "critère_n2_parent_isolé_date_certification": None,
            "critère_n2_parent_isolé_période_certification": None,
            "critère_n2_personne_sans_hébergement_ou_hébergée_ou_ayant_u": 0,
            "critère_n2_réfugié_statutaire_bénéficiaire_d_une_protectio": 0,
            "critère_n2_résident_zrr": 0,
            "critère_n2_résident_qpv": 0,
            "critère_n2_sortant_de_détention_ou_personne_placée_sous_main": 0,
            "critère_n2_maîtrise_de_la_langue_française": 0,
            "critère_n2_mobilité": 0,
            "injection_ai": 0,
            "date_mise_à_jour_metabase": timezone.localdate() - datetime.timedelta(days=1),
        },
    ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_criteria():
    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count criteria
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select criteria IDs
    num_queries += 1  # Select one chunk of criteria IDs
    num_queries += 1  # Select criteria with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
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
def test_populate_job_applications():
    create_test_romes_and_appellations(["M1805"], appellations_per_rome=1)
    company = CompanyFactory(
        for_snapshot=True,
        siret="12989128580059",
        # also means that the SIAE will be active, thus the job description also will be.
        # this would also be a source of flakyness if not enforced.
        kind="GEIQ",
    )
    job = JobDescriptionFactory(is_active=True, company=company)
    ja = JobApplicationFactory(
        with_geiq_eligibility_diagnosis=True,
        contract_type=ContractType.APPRENTICESHIP,
        state=JobApplicationState.ACCEPTED,
    )
    ja.selected_jobs.add(job)

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Select siaes for get_active_companies_pks()
    num_queries += 1  # Count job applications
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select job application IDs
    num_queries += 1  # Select one chunk of job application IDs
    num_queries += 1  # Select job applications with columns
    num_queries += 1  # Select job application transition logs
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="job_applications")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM candidatures ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                ja.pk,
                False,  # archived_at
                False,  # auto rerused
                ja.created_at.date(),
                ja.hiring_start_at,
                ja.processed_at.date(),
                "Candidature acceptée",
                "Orienteur",
                "Orienteur sans organisation",
                None,
                "default",
                None,
                None,
                None,
                ja.job_seeker_id,
                ja.to_company_id,
                ja.to_company.kind,
                ja.to_company.display_name,
                f"{ja.to_company.kind} - ID {ja.to_company_id} - {ja.to_company.display_name}",
                ja.to_company.department,
                DEPARTMENTS.get(ja.to_company.department),
                ja.to_company.region,
                None,
                None,
                None,
                None,
                None,
                False,
                "",
                ja.contract_type,
                True,
                datetime.date(2023, 2, 1),
            ),
        ]

    # no need for a cache clear for the active siae pks, has been done above
    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count job applications
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select job application IDs
    num_queries += 1  # Select one chunk of job application IDs
    num_queries += 1  # Select job applications with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="selected_jobs")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM fiches_de_poste_par_candidature ORDER BY id_candidature")
        rows = cursor.fetchall()
        assert rows == [
            (
                job.pk,
                ja.pk,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_approvals():
    approval = ApprovalFactory()
    pe_approval = PoleEmploiApprovalFactory()

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count approvals
    num_queries += 1  # Count PE approvals
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select approval IDs
    num_queries += 1  # Select approvals IDs, chunk by 1000
    num_queries += 1  # Select approvals with columns
    num_queries += 1  # Prefetch users
    num_queries += 1  # Prefetch JobApplications
    num_queries += 1  # COMMIT (inject_chunk)

    num_queries += 1  # Select PE approval IDs
    num_queries += 1  # Select PE approvals IDs, chunk by 1000
    num_queries += 1  # Select PE approvals with columns
    num_queries += 1  # Select prescriber organizations
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="approvals")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM pass_agréments ORDER BY date_début")
        rows = cursor.fetchall()
        assert rows == [
            (
                approval.pk,
                "PASS IAE (XXXXX)",
                datetime.date(2023, 2, 2),
                datetime.date(2025, 1, 31),
                datetime.timedelta(days=729),
                approval.user.id,
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
                pe_approval.pk,
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
                0,
                hash_content(pe_approval.number),
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_prolongations():
    prolongation = ProlongationFactory(with_request=True)
    prolongation_request = prolongation.request

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count prolongations
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select prolongation IDs
    num_queries += 1  # Select one chunk of prolongation IDs
    num_queries += 1  # Select prolongations with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="prolongations")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM prolongations ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                prolongation.id,
                prolongation.approval_id,
                prolongation.start_at,
                prolongation.end_at,
                prolongation.get_reason_display(),
                prolongation.declared_by_id,
                prolongation.declared_by_siae_id,
                prolongation.validated_by_id,
                prolongation.prescriber_organization_id,
                prolongation.created_at.date(),
                prolongation_request.pk,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_prolongation_requests():
    prolongation = ProlongationFactory(with_request=True)
    prolongation_request = prolongation.request

    deny_information = ProlongationRequestDenyInformationFactory.build(request=None)
    with transaction.atomic():
        prolongation_request.deny(prolongation_request.validated_by, deny_information)

    ProlongationFactory(with_request=True)  # add another one to ensure we don't fail without a deny_information

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count prolongation_requests
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select prolongation_request IDs
    num_queries += 1  # Select one chunk of prolongation_request IDs
    num_queries += 1  # Select prolongation_requests with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="prolongation_requests")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM demandes_de_prolongation ORDER BY id")
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert rows[0] == (
            prolongation_request.id,
            prolongation_request.approval_id,
            prolongation_request.start_at,
            prolongation_request.end_at,
            prolongation_request.get_reason_display(),
            prolongation_request.declared_by_id,
            prolongation_request.declared_by_siae_id,
            prolongation_request.validated_by_id,
            prolongation_request.prescriber_organization_id,
            prolongation.pk,
            prolongation_request.get_status_display(),
            str(deny_information.reason),
            prolongation_request.created_at.date(),
            prolongation_request.processed_at,
            prolongation_request.processed_by_id,
            prolongation_request.reminder_sent_at,
            datetime.date(2023, 2, 1),
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_suspensions():
    suspension = SuspensionFactory()

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count Suspensions
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select pks
    num_queries += 1  # Select one chunk
    num_queries += 1  # Select queryset with annotations
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="suspensions")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM suspensions_v0 ORDER BY id")
        rows = dictfetchall(cursor)

    assert rows == [
        {
            "id": suspension.id,
            "id_pass_agrément": suspension.approval_id,
            "date_début": suspension.start_at,
            "date_fin": suspension.end_at,
            "motif": suspension.reason.value,
            "en_cours": int(suspension.is_in_progress),
            "date_de_création": suspension.created_at,
            "date_mise_à_jour_metabase": timezone.localdate() - datetime.timedelta(days=1),
        }
    ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_institutions():
    institution = InstitutionFactory(department="14")

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count institutions
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select institution IDs
    num_queries += 1  # Select one chunk of institution IDs
    num_queries += 1  # Select institutions with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
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

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count campaigns
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select campaign IDs
    num_queries += 1  # Select one chunk of campaign IDs
    num_queries += 1  # Select campaigns with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
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

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count evaluated siaes
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select evaluated siae IDs
    num_queries += 1  # Select one chunk of evaluated siae IDs
    num_queries += 1  # Select evaluated siaes with columns
    num_queries += 1  # Select related evaluated job applications
    num_queries += 1  # Select related campaigns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
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

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count evaluated job applications
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select evaluated job application IDs
    num_queries += 1  # Select one chunk of evaluated job application IDs
    num_queries += 1  # Select evaluated job applications with columns
    num_queries += 1  # Select related evaluated siaes
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="evaluated_job_applications")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM cap_candidatures ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                evaluated_job_application.id,
                evaluated_job_application.job_application_id,
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

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count evaluated criteria
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select evaluated criteria IDs
    num_queries += 1  # Select one chunk of evaluated criteria IDs
    num_queries += 1  # Select evaluated criteria with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
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


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_users_exclude_job_seekers():
    """
    Job seeker personal data (email...) should never ever ever ever ever ever end up in Metabase.
    Only pro users end up there.
    """
    JobSeekerFactory()
    management.call_command("populate_metabase_emplois", mode="users")
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM utilisateurs_v0 ORDER BY id")
        rows = cursor.fetchall()
        assert len(rows) == 0


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_users():
    pro_user = EmployerFactory()

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count users
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select user IDs
    num_queries += 1  # Select one chunk of user IDs
    num_queries += 1  # Select users with columns
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="users")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM utilisateurs_v0 ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                pro_user.id,
                pro_user.email,
                "employer",
                pro_user.first_name,
                pro_user.last_name,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_memberships():
    company_membership = CompanyMembershipFactory()
    CompanyMembershipFactory(is_active=False)  # Inactive siae memberships are ignored.
    CompanyMembershipFactory(user__is_active=False)  # memberships of inactive users are also ignored
    prescriber_membership = PrescriberMembershipFactory()
    PrescriberMembershipFactory(is_active=False)
    PrescriberMembershipFactory(user__is_active=False)
    institution_membership = InstitutionMembershipFactory()
    InstitutionMembershipFactory(is_active=False, institution=institution_membership.institution)
    InstitutionMembershipFactory(user__is_active=False, institution=institution_membership.institution)

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count siae memberships
    num_queries += 1  # Count prescriber memberships
    num_queries += 1  # Count institution memberships

    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table

    num_queries += 1  # Select siae memberships IDs
    num_queries += 1  # Select one chunk of siae memberships IDs
    num_queries += 1  # Select siae memberships with columns
    num_queries += 1  # COMMIT (inject_chunk)

    num_queries += 1  # Select prescriber memberships IDs
    num_queries += 1  # Select one chunk of prescriber memberships IDs
    num_queries += 1  # Select prescriber memberships with columns
    num_queries += 1  # COMMIT (inject_chunk)

    num_queries += 1  # Select institution memberships IDs
    num_queries += 1  # Select one chunk of institution memberships IDs
    num_queries += 1  # Select institution memberships with columns
    num_queries += 1  # COMMIT (inject_chunk)

    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="memberships")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM collaborations ORDER BY id_utilisateur")
        rows = cursor.fetchall()
        assert rows == [
            (
                company_membership.user_id,
                True,
                company_membership.company_id,
                None,
                None,
                datetime.date(2023, 2, 1),
            ),
            (
                prescriber_membership.user_id,
                True,
                None,
                prescriber_membership.organization_id,
                None,
                datetime.date(2023, 2, 1),
            ),
            (
                institution_membership.user_id,
                True,
                None,
                None,
                institution_membership.institution_id,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_enums():
    num_queries = 1  # COMMIT Create table
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries *= 5  # We inject thus many enums so far.
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="enums")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_ref_origine_candidature ORDER BY code")
        rows = cursor.fetchall()
        assert rows == [
            ("admin", "Créée depuis l'admin"),
            ("ai_stock", "Créée lors de l'import du stock AI"),
            ("default", "Créée normalement via les emplois"),
            ("pe_approval", "Créée lors d'un import d'Agrément Pole Emploi"),
        ]

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_ref_type_contrat ORDER BY code")
        rows = cursor.fetchall()
        assert rows[0] == ("APPRENTICESHIP", "Contrat d'apprentissage")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_ref_type_prescripteur ORDER BY code")
        rows = cursor.fetchall()
        assert rows[0] == ("AFPA", "AFPA - Agence nationale pour la formation professionnelle des adultes")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_ref_motif_de_refus ORDER BY code")
        rows = cursor.fetchall()
        assert rows[0] == ("approval_expiration_too_close", "La date de fin du PASS IAE / agrément est trop proche")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_ref_motif_suspension ORDER BY code")
        rows = cursor.fetchall()
        assert rows[0] == (
            "APPROVAL_BETWEEN_CTA_MEMBERS",
            "Situation faisant l'objet d'un accord entre les acteurs membres du CTA (Comité technique d'animation)",
        )


def test_data_inconsistencies(caplog):
    approval = ApprovalFactory()

    with assertNumQueries(2):  # SELECT set_config() + Select the job seekers
        management.call_command("populate_metabase_emplois", mode="data_inconsistencies")

    logs = caplog.messages
    assert logs[0] == "Checking data for inconsistencies."
    assert "timeit: method=report_data_inconsistencies completed in seconds=" in logs[1]
    assert "timeit: method=handle completed in seconds=" in logs[2]

    approval.user.kind = UserKind.EMPLOYER
    approval.user.save()

    caplog.clear()
    with pytest.raises(RuntimeError):
        management.call_command("populate_metabase_emplois", mode="data_inconsistencies")
    assert caplog.messages[:-1] == [
        "Checking data for inconsistencies.",
        "FATAL ERROR: At least one user has an approval but is not a job seeker",
        "Error when executing itou.metabase.management.commands.populate_metabase_emplois",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.metabase.management.commands.populate_metabase_emplois failed in"
    )


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_job_descriptions():
    create_test_romes_and_appellations(["M1805"], appellations_per_rome=1)
    company = CompanyFactory(
        for_snapshot=True,
        siret="12989128580059",
        # also means that the SIAE will be active, thus the job description also will be.
        # this would also be a source of flakyness if not enforced.
        kind="GEIQ",
    )
    job = JobDescriptionFactory(is_active=False, company=company)

    # trigger the first .from_db() call and populate _old_is_active.
    # please note that .refresh_from_db() would call .from_db() but _old_is_active
    # would not be populated since the instances in memory would be different.
    job = JobDescription.objects.get(pk=job.pk)
    assert job._old_is_active is False
    assert job.field_history == []

    # modify the field
    job.is_active = True
    job.save(update_fields=["is_active", "updated_at"])
    job = JobDescription.objects.get(pk=job.pk)
    assert job.field_history == [
        {
            "field": "is_active",
            "from": False,
            "to": True,
            "at": "2023-02-02T00:00:00Z",
        }
    ]

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count total rows for job descriptions
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select all job descriptions
    num_queries += 1  # Select job descriptions chunk
    num_queries += 1  # Select job descriptions with columns
    num_queries += 1  # Annotate job applications count
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="job_descriptions")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM fiches_de_poste ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                job.pk,
                "M1805",
                "Études et développement informatique",
                1,
                job.contract_type,
                company.pk,
                "GEIQ",
                "12989128580059",
                "Acme inc.",
                '[{"at": "2023-02-02T00:00:00Z", "to": true, "from": false, "field": "is_active"}]',
                "75",
                "75 - Paris",
                "Île-de-France",
                0,
                datetime.date(2023, 2, 2),
                datetime.date(2023, 2, 2),
                datetime.date(2023, 2, 1),
            ),
        ]

    # ensure the JSON is readable and is not just a plain string
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT id, mises_a_jour_champs->0->'to' from fiches_de_poste WHERE id = {job.pk}")
        rows = cursor.fetchall()
        assert rows == [(job.pk, "true")]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_companies():
    company = CompanyFactory(
        for_snapshot=True,
        siret="17643069438162",
        naf="1071A",
        email="contact@garaje_el_martinet.es",
        auth_email="secret.ceo@garaje_el_martinet.es",
        with_membership=True,
        with_jobs=True,
        coords="POINT (5.43567 12.123876)",
    )
    # Add an inactive membership, and a active membership on an inactive user
    # both should be ignored in total_members aggregation
    CompanyMembershipFactory(company=company, is_active=False)
    CompanyMembershipFactory(company=company, user__is_active=False)

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count Siaes
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select active SIAES
    num_queries += 1  # Select one chunk of siaes
    num_queries += 1  # Select siaes with annotations and columns
    num_queries += 1  # Select other siaes with the same convention
    num_queries += 1  # Prefetch siae job descriptions
    num_queries += 1  # Prefetch siae active memberships (for total_membres)
    num_queries += 1  # Prefetch siae memberships (for first_membership_join_date)
    num_queries += 1  # Prefetch siae members (for members last_login)
    num_queries += 1  # Prefetch cities
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="siaes")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM structures_v0 ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                company.pk,
                company.convention.asp_id,
                "Acme inc.",
                f"EI - ID {company.pk} - Acme inc.",
                "",
                "EI",
                "17643069438162",
                "Export ASP",
                "1071A",
                "contact@garaje_el_martinet.es",
                "secret.ceo@garaje_el_martinet.es",
                False,
                # Address columns " de la structure mère"
                "112 rue de la Croix-Nivert",
                "",
                "75015",
                None,
                "Paris",
                5.43567,
                12.123876,
                "75",
                "75 - Paris",
                "Île-de-France",
                # Address columns " de la structure C1"
                "112 rue de la Croix-Nivert",
                "",
                "75015",
                None,
                "Paris",
                5.43567,
                12.123876,
                "75",
                "75 - Paris",
                "Île-de-France",
                datetime.date(2023, 2, 2),
                1,
                0,
                0,
                0,
                0,
                0.0,
                0,
                0,
                0,
                0,
                0,
                None,
                0,
                None,
                4,
                0,
                datetime.date(2023, 2, 1),
            ),
        ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_companies_convergence(settings):
    convergence_company = CompanyFactory(kind=CompanyKind.ACI)
    settings.ACI_CONVERGENCE_SIRET_WHITELIST = [convergence_company.siret]
    aci_non_convergence_company = CompanyFactory(kind=CompanyKind.ACI)
    non_convergence_company = CompanyFactory()

    management.call_command("populate_metabase_emplois", mode="siaes")
    with connection.cursor() as cursor:
        cursor.execute("SELECT siret, convergence_france FROM structures_v0 ORDER BY id")
        assert cursor.fetchall() == [
            (convergence_company.siret, True),
            (aci_non_convergence_company.siret, False),
            (non_convergence_company.siret, False),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_gps_groups():
    group = FollowUpGroupFactory(for_snapshot=True)

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count FollowUpGroups
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select FollowUpGroups pks
    num_queries += 1  # Select one chunk of FollowUpGroups
    num_queries += 1  # Select FollowUpGroups with annotations
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="gps_groups")

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {gps.GroupsTable.name} ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                group.pk,
                group.created_at,
                group.updated_at,
                group.created_in_bulk,
                group.beneficiary.department,
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_gps_memberships():
    membership = FollowUpGroupMembershipFactory(follow_up_group__for_snapshot=True, member__for_snapshot=True)
    prescriber = membership.member
    PrescriberMembershipFactory(user=prescriber, organization__department="63")
    PrescriberMembershipFactory(user=prescriber, organization__department="13")
    PrescriberMembershipFactory(user=prescriber, organization__department="75")

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Count FollowUpGroupMemberships
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT Create table
    num_queries += 1  # Select FollowUpGroupMemberships pks
    num_queries += 1  # Select one chunk of FollowUpGroupMemberships
    num_queries += 1  # Select FollowUpGroupMemberships with annotations
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="gps_memberships")

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {gps.MembershipsTable.name} ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                membership.pk,
                membership.follow_up_group.pk,
                membership.created_at,
                membership.updated_at,
                membership.ended_at,
                membership.member.pk,
                ["13", "63", "75"],
                int(membership.created_in_bulk),
                datetime.date(2023, 2, 1),
            ),
        ]


@freeze_time("2023-02-02")
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_organizations():
    first_organisation = PrescriberOrganizationWith2MembershipFactory(
        authorized=True,
        post_code="59473",
    )
    second_organisation = PrescriberOrganizationFactory(
        authorized=True,
        post_code="63020",
    )
    # Add an inactive membership, and a active membership on an inactive user
    # both should be ignored in total_members aggregation
    PrescriberMembershipFactory(organization=first_organisation, is_active=False)
    PrescriberMembershipFactory(organization=first_organisation, user__is_active=False)

    num_queries = 1  # SELECT set_config()
    num_queries += 1  # Select get_active_companies_pks()
    num_queries += 1  # Count organization
    num_queries += 1  # COMMIT Queryset counts (autocommit mode)
    num_queries += 1  # COMMIT get_active_companies_pks (autocommit mode)
    num_queries += 1  # Select cities
    num_queries += 1  # Count memberships
    num_queries += 2  # Select members/prescribermembership_set for ORG_OF_PRESCRIBERS_WITHOUT_ORG
    num_queries += 1  # COMMIT Create table

    num_queries += 1  # Select organization IDs
    num_queries += 1  # Select one chunk of organization IDs
    num_queries += 1  # Select organization with columns
    num_queries += 1  # Select prefetch organizations active memberships (for total_membres)
    num_queries += 1  # Select prefetch organizations memberships (for first_membership_join_date)
    num_queries += 1  # Select prefetch organizations members (for members last_login)
    num_queries += 1  # COMMIT (inject_chunk)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically RENAME TABLE)
    num_queries += 1  # COMMIT (rename_table_atomically DROP TABLE)
    with assertNumQueries(num_queries):
        management.call_command("populate_metabase_emplois", mode="organizations")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM organisations_v0 ORDER BY id")
        rows = cursor.fetchall()
        assert rows == [
            (
                -1,
                None,
                "Regroupement des prescripteurs sans organisation",
                None,
                None,
                0,
                "",
                "",
                "",
                None,
                "",
                None,
                None,
                "",
                None,
                None,
                None,
                None,
                0,
                0,
                0,
                None,
                None,
                0,
                0,
                datetime.date(2023, 2, 1),
            ),
            (
                first_organisation.pk,
                first_organisation.siret,
                first_organisation.name,
                "FT",
                "France Travail",
                1,
                "",
                "",
                "59473",
                None,
                "",
                None,
                None,
                "59",
                "59 - Nord",
                "Hauts-de-France",
                datetime.date(2023, 2, 2),
                None,
                2,
                0,
                0,
                None,
                None,
                0,
                0,
                datetime.date(2023, 2, 1),
            ),
            (
                second_organisation.pk,
                second_organisation.siret,
                second_organisation.name,
                "FT",
                "France Travail",
                1,
                "",
                "",
                "63020",
                None,
                "",
                None,
                None,
                "63",
                "63 - Puy-de-Dôme",
                "Auvergne-Rhône-Alpes",
                None,
                None,
                0,
                0,
                0,
                None,
                None,
                0,
                0,
                datetime.date(2023, 2, 1),
            ),
        ]
