import datetime

import pytest
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertFormError, assertNotContains, assertRedirects

from itou.companies.enums import CompanyKind
from itou.geiq.models import ReviewState
from itou.institutions.enums import InstitutionKind
from itou.users.enums import Title
from itou.utils.apis import geiq_label
from itou.utils.urls import get_absolute_url
from itou.www.geiq_views.views import InfoType
from tests.cities.factories import create_city_vannes
from tests.companies.factories import (
    CompanyMembershipFactory,
)
from tests.files.factories import FileFactory
from tests.geiq.factories import (
    EmployeeFactory,
    ImplementationAssessmentCampaignFactory,
    ImplementationAssessmentFactory,
    SalarieContratLabelDataFactory,
    SalariePreQualificationLabelDataFactory,
)
from tests.institutions.factories import InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerFactory, LaborInspectorFactory
from tests.utils.test import parse_response_to_soup


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


def test_assessment_process_for_geiq(client, label_settings, mailoutbox, mocker, pdf_file):
    membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ, company__department="29")
    assessment = ImplementationAssessmentFactory(campaign__year=2023, company=membership.company)
    geiq_user = membership.user

    ddets_membership = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DDETS_GEIQ,
        institution__department=membership.company.department,
    )
    dreets_membership = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DREETS_GEIQ,
        institution__department=membership.company.department,
    )
    # Add a user of both DDETS & DREETS
    both_institution_user = InstitutionMembershipFactory(institution=dreets_membership.institution).user
    InstitutionMembershipFactory(institution=ddets_membership.institution, user=both_institution_user)

    client.force_login(geiq_user)
    assessment_info_url = reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk})
    response = client.get(assessment_info_url)
    employee_list_url = reverse(
        "geiq:employee_list", kwargs={"assessment_pk": assessment.pk, "info_type": "personal-information"}
    )
    assertContains(
        response,
        '<span class="badge badge-sm rounded-pill text-nowrap bg-warning">En attente du bilan d’exécution</span>',
    )
    assertContains(response, "Importer un fichier")
    assertContains(response, "Dernière synchronisation: -")
    assertContains(
        response,
        f'<a href="{employee_list_url}" class="btn btn-outline-primary ">Consulter les données salariés</a>',
    )
    assertContains(response, "Mettre à jour")

    contract = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_id,
        salarie__statuts_prioritaire=[
            {"id": 13, "libelle": "Bénéficiaire du RSA", "libelle_abr": "RSA", "niveau": 1},
        ],
        date_debut="2023-01-01T00:00:00+01:00",
        date_fin="2024-01-31:00:00+01:00",
    )
    contract_with_prequal = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_id,
        salarie__statuts_prioritaire=[
            {"id": 21, "libelle": "Travailleur handicapé", "libelle_abr": "TH", "niveau": 2},
        ],
        date_debut="2023-01-15:00:00+01:00",
        date_fin="2023-01-31:00:00+01:00",
        date_fin_contrat="2023-01-31:00:00+01:00",
    )
    prequal_of_contract = SalariePreQualificationLabelDataFactory(
        salarie=dict(contract_with_prequal["salarie"]),  # Make a copy since sync function modifies the received data
        date_debut="2022-12-15:00:00+01:00",
        date_fin="2023-01-10:00:00+01:00",
    )

    def _fake_get_all_contracts(self, geiq_id):
        assert geiq_id == assessment.label_id
        return [dict(contract), dict(contract_with_prequal)]

    def _fake_get_all_prequalifications(self, geiq_id):
        assert geiq_id == assessment.label_id
        return [prequal_of_contract]

    mocker.patch.object(geiq_label.LabelApiClient, "get_all_contracts", _fake_get_all_contracts)
    mocker.patch.object(geiq_label.LabelApiClient, "get_all_prequalifications", _fake_get_all_prequalifications)

    response = client.post(reverse("geiq:label_sync", kwargs={"assessment_pk": assessment.pk}))
    assessment.refresh_from_db()
    assert assessment.last_synced_at is not None
    assertContains(response, "Dernière synchronisation:")

    assert mailoutbox == []
    response = client.post(
        assessment_info_url,
        data={"activity_report_file": pdf_file, "up_to_date_information": True},
    )
    [institution_email] = mailoutbox
    assert sorted(institution_email.to) == sorted(
        [ddets_membership.user.email, dreets_membership.user.email, both_institution_user.email]
    )
    assert assessment.company.display_name in institution_email.subject
    assert assessment.company.display_name in institution_email.body
    assert get_absolute_url(assessment_info_url) in institution_email.body
    assertContains(
        response,
        '<span class="badge badge-sm rounded-pill text-nowrap bg-info">Bilan à l’étude</span>',
    )
    assessment.refresh_from_db()
    assert assessment.submitted_at is not None
    assert assessment.submitted_by == geiq_user
    pdf_file.seek(0)
    with default_storage.open(assessment.activity_report_file_id) as saved_report:
        assert saved_report.read() == pdf_file.read()

    # Check access to uploaded report
    report_url = reverse("geiq:assessment_report", kwargs={"assessment_pk": assessment.pk})
    assertContains(response, report_url)
    # Boto3 signed requests depend on the current date, with a second resolution.
    # See X-Amz-Date in
    # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
    with freeze_time():
        response = client.get(report_url)
        assertRedirects(
            response, default_storage.url(assessment.activity_report_file_id), fetch_redirect_response=False
        )

    institution_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment.reviewed_at = timezone.now()
    assessment.reviewed_by = institution_membership.user
    assessment.review_institution = institution_membership.institution
    assessment.review_state = ReviewState.ACCEPTED
    assessment.review_comment = "Bon boulot !"
    assessment.save()

    response = client.get(assessment_info_url)
    assertContains(
        response,
        (
            '<span class="badge badge-sm rounded-pill text-nowrap bg-success">'
            "Financement : totalité de l’aide accordée</span>"
        ),
    )


def test_geiq_list_assessment_visibility(client):
    user = LaborInspectorFactory()
    ddets = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DDETS_GEIQ,
        institution__department=29,
        user=user,
    ).institution
    ddets_url = reverse("geiq:geiq_list", kwargs={"institution_pk": ddets.pk})
    # DREETS from Bretagne region with access to GEIQ of departments 22, 29, 35, 56
    dreets = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DREETS_GEIQ,
        institution__department=29,
        user=user,
    ).institution
    dreets_url = reverse("geiq:geiq_list", kwargs={"institution_pk": dreets.pk})
    client.force_login(user)

    campaign_2023 = ImplementationAssessmentCampaignFactory(year=2023)
    campaign_2024 = ImplementationAssessmentCampaignFactory(year=2024)
    # Outside of Bretagne
    outside_bretagne_assessment = ImplementationAssessmentFactory(
        campaign=campaign_2023,
        company__department=33,
        company__name="GEIQ hors de Bretagne",
    )
    geiq_29_2023_assessment = ImplementationAssessmentFactory(
        campaign=campaign_2023,
        company__department=29,
        company__name="GEIQ du Finistère",
    )
    geiq_29_2024_assessment = ImplementationAssessmentFactory(
        campaign=campaign_2024,
        company=geiq_29_2023_assessment.company,
    )
    geiq_56_2023_assessment = ImplementationAssessmentFactory(
        campaign=campaign_2023,
        company__department=56,
        company__name="GEIQ du Morbihan",
    )

    def _get_assessment_url(assessment):
        return reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk})

    dreets_response = client.get(dreets_url)
    ddets_response = client.get(ddets_url)

    # Outside of both DDETS & DREETS scope
    assertNotContains(dreets_response, _get_assessment_url(outside_bretagne_assessment))
    assertNotContains(ddets_response, _get_assessment_url(outside_bretagne_assessment))

    # Inside both DDETS & DREETS scope (and 2024 is the latest)
    assertContains(dreets_response, _get_assessment_url(geiq_29_2024_assessment))
    assertContains(ddets_response, _get_assessment_url(geiq_29_2024_assessment))

    # Inside both DDETS & DREETS scope but 2023 is not the latest one
    assertNotContains(dreets_response, _get_assessment_url(geiq_29_2023_assessment))
    assertNotContains(ddets_response, _get_assessment_url(geiq_29_2023_assessment))

    # Only inside DREETS scope
    assertContains(dreets_response, _get_assessment_url(geiq_56_2023_assessment))
    assertNotContains(ddets_response, _get_assessment_url(geiq_56_2023_assessment))


def test_geiq_list_snapshots(client, snapshot):
    membership = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DREETS_GEIQ,
        institution__department=29,
    )
    url = reverse("geiq:geiq_list", kwargs={"institution_pk": membership.institution.pk})
    client.force_login(membership.user)

    response = client.get(url)
    assert str(parse_response_to_soup(response, selector="#main .s-section")) == snapshot(name="empty list")

    campaign = ImplementationAssessmentCampaignFactory(year=2023)

    assessments = [
        ImplementationAssessmentFactory(
            campaign=campaign,
            company__department=56,
            company__name="GEIQ du Morbihan",
            company__insee_city=create_city_vannes(),
        ),
        ImplementationAssessmentFactory(
            campaign=campaign,
            company__department=29,
            company__name="GEIQ du Finistère avec bilan transmis",
            company__city="Porspoder",
            last_synced_at=datetime.datetime(2024, 6, 1, 0, 0, 0, tzinfo=datetime.UTC),
            submitted_at=datetime.datetime(2024, 7, 1, 0, 0, 0, tzinfo=datetime.UTC),
            activity_report_file=FileFactory(for_snapshot=True),
        ),
    ]
    EmployeeFactory(assessment=assessments[0], allowance_amount=1400)
    EmployeeFactory(assessment=assessments[1], allowance_amount=0)
    for i, review_state in enumerate(ReviewState, start=1):
        assessments.append(
            ImplementationAssessmentFactory(
                campaign=campaign,
                company__department=35,
                company__city="Rennes",
                company__name=f"GEIQ d’Ille-et-Vilaine {review_state}",
                last_synced_at=datetime.datetime(2024, 6, 1, 0, 0, 0, tzinfo=datetime.UTC),
                submitted_at=datetime.datetime(2024, 7, 1, 0, 0, 0, tzinfo=datetime.UTC),
                activity_report_file=FileFactory(key=f"report for {review_state}"),
                review_comment="Un commentaire",
                reviewed_at=datetime.datetime(2024, 8, 1, 0, 0, 0, tzinfo=datetime.UTC),
                review_institution=membership.institution,
                review_state=review_state,
            )
        )
        EmployeeFactory.create_batch(i, assessment=assessments[-1], allowance_amount=1400)

    response = client.get(url)
    assert str(
        parse_response_to_soup(
            response,
            selector="#main .s-section",
            replace_in_attr=[
                ("href", f"/geiq/assessment/{assessment.pk}", "/geiq/assessment/[PK of ImplementationAssessment]")
                # Make sure we replace pks starting from the biggest
                # otherwise replacing "/geiq/assessment/1" would prevent "/geiq/assessment/12" replacement
                for assessment in sorted(assessments, key=lambda a: -a.pk)
            ],
        )
    ) == snapshot(name="different states list")


def test_geiq_list_no_access(client, snapshot):
    membership = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DDETS_GEIQ,
        institution__department=29,
    )
    url = reverse("geiq:geiq_list", kwargs={"institution_pk": membership.institution.pk})

    # DDETS GEIQ OK
    client.force_login(membership.user)
    response = client.get(url)
    assert response.status_code == 200

    # DDETS IAE KO
    client.force_login(
        InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DDETS_IAE,
            institution__department=29,
        ).user
    )
    response = client.get(url)
    assert response.status_code == 404

    # JobSeeker
    client.force_login(JobSeekerFactory())
    response = client.get(url)
    assertRedirects(response, reverse("account_login"), fetch_redirect_response=False)

    # Prescriber
    client.force_login(PrescriberMembershipFactory(organization__authorized=True).user)
    response = client.get(url)
    assertRedirects(response, reverse("account_login"), fetch_redirect_response=False)

    # Employer
    client.force_login(CompanyMembershipFactory(company__kind=CompanyKind.GEIQ, company__department=29).user)
    response = client.get(url)
    assertRedirects(response, reverse("account_login"), fetch_redirect_response=False)


def test_state_snapshot(client, snapshot):
    geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ, company__for_snapshot=True)
    assessment = ImplementationAssessmentFactory(campaign__year=2023, company=geiq_membership.company)
    geiq_user = geiq_membership.user
    institution_membership = InstitutionMembershipFactory(
        user__last_name="GADGET",
        user__first_name="Inspecteur",
        institution__kind=InstitutionKind.DDETS_GEIQ,
        institution__department=75,
        institution__name="DDETS 75",
    )
    ddets = institution_membership.institution
    ddets_user = institution_membership.user
    assessment_info_url = reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk})

    def check_snapshots(user, snapshot_name):
        client.force_login(user)
        response = client.get(assessment_info_url)
        assert str(
            parse_response_to_soup(
                response,
                selector="#main .s-title-02",
                replace_in_attr=[
                    (
                        "href",
                        f"/geiq/list/{ddets.pk}",
                        "/geiq/list/[PK of Institution]",
                    ),
                ],
            )
        ) == snapshot(name=f"{snapshot_name} / title")
        assert str(
            parse_response_to_soup(
                response,
                selector="#main .s-section",
                replace_in_attr=[
                    (
                        "href",
                        f"/geiq/assessment/{assessment.pk}/",
                        "/geiq/assessment/[PK of ImplementationAssessment]/",
                    ),
                    (
                        "href",
                        f"/company/{geiq_membership.company.pk}/card",
                        "/company/[PK of Company]/card",
                    ),
                    (
                        "hx-post",
                        f"/geiq/assessment/{assessment.pk}/",
                        "/geiq/assessment/[PK of ImplementationAssessment]/",
                    ),
                ],
            )
        ) == snapshot(name=f"{snapshot_name} / main section")

    # Unsubmitted assessment
    check_snapshots(geiq_user, "unsubmitted assessment as GEIQ")
    check_snapshots(ddets_user, "unsubmitted assessment as DDETS")

    # Submitted assessment
    assessment.last_synced_at = datetime.datetime(2024, 6, 1, 0, 0, 0, tzinfo=datetime.UTC)
    assessment.submitted_at = datetime.datetime(2024, 7, 1, 0, 0, 0, tzinfo=datetime.UTC)
    assessment.submitted_by = geiq_user
    assessment.activity_report_file = FileFactory(for_snapshot=True)
    assessment.save()

    check_snapshots(geiq_user, "submitted assessment as GEIQ")
    check_snapshots(ddets_user, "submitted assessment as DDETS")

    # Fully accepted assessment
    assessment.reviewed_by = ddets_user
    assessment.review_institution = ddets
    assessment.reviewed_at = datetime.datetime(2024, 8, 1, 0, 0, 0, tzinfo=datetime.UTC)
    assessment.review_state = ReviewState.ACCEPTED
    assessment.review_comment = "Bravo"
    assessment.save()

    check_snapshots(geiq_user, "fully accepted assessment as GEIQ")
    check_snapshots(ddets_user, "fully accepted assessment as DDETS")

    # Partial accepted assessment
    assessment.review_state = ReviewState.PARTIAL_ACCEPTED
    assessment.review_comment = "Presque bravo"
    assessment.save()

    check_snapshots(geiq_user, "partial accepted assessment as GEIQ")
    check_snapshots(ddets_user, "partial accepted assessment as DDETS")

    # Remainder refused assessment
    assessment.review_state = ReviewState.REMAINDER_REFUSED
    assessment.review_comment = "Mouais"
    assessment.save()

    check_snapshots(geiq_user, "remainder refused assessment as GEIQ")
    check_snapshots(ddets_user, "remainder refused assessment as DDETS")

    # Partial refund assessment
    assessment.review_state = ReviewState.PARTIAL_REFUND
    assessment.review_comment = "Pas top"
    assessment.save()

    check_snapshots(geiq_user, "partial refund assessment as GEIQ")
    check_snapshots(ddets_user, "partial refund assessment as DDETS")

    # Full refund assessment
    assessment.review_state = ReviewState.FULL_REFUND
    assessment.review_comment = "Non !"
    assessment.save()

    check_snapshots(geiq_user, "full refund assessment as GEIQ")
    check_snapshots(ddets_user, "full refund assessment as DDETS")


def test_review(client):
    assessment = ImplementationAssessmentFactory(
        company__department=29,
        last_synced_at=datetime.datetime(2024, 5, 1, 0, 0, 0, tzinfo=datetime.UTC),
        submitted_at=datetime.datetime(2024, 6, 1, 0, 0, 0, tzinfo=datetime.UTC),
        activity_report_file=FileFactory(for_snapshot=True),
    )
    membership = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DDETS_GEIQ,
        institution__department=assessment.company.department,
    )
    ddets_user = membership.user
    ddets = membership.institution
    client.force_login(ddets_user)
    info_url = reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk})
    report_url = reverse("geiq:assessment_report", kwargs={"assessment_pk": assessment.pk})
    review_url = reverse("geiq:assessment_review", kwargs={"assessment_pk": assessment.pk})

    response = client.get(info_url)
    assertContains(response, review_url)
    assertContains(response, report_url)

    # Check access to report
    # Boto3 signed requests depend on the current date, with a second resolution.
    # See X-Amz-Date in
    # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
    with freeze_time():
        response = client.get(report_url)
        assertRedirects(
            response, default_storage.url(assessment.activity_report_file_id), fetch_redirect_response=False
        )

    # Start review
    response = client.get(review_url)
    assertContains(response, "Valider le bilan d’exécution")

    response = client.post(
        review_url,
        data={
            "review_state": "",
            "review_comment": "",
        },
    )
    assertContains(response, "Ce champ est obligatoire.")
    assertFormError(response.context["form"], "review_state", ["Ce champ est obligatoire."])
    assertFormError(response.context["form"], "review_comment", ["Ce champ est obligatoire."])

    response = client.post(
        review_url,
        data={
            "review_state": ReviewState.PARTIAL_ACCEPTED,
            "review_comment": "En partie bien",
        },
    )
    assertRedirects(response, info_url)

    assessment.refresh_from_db()
    assert assessment.reviewed_at is not None
    assert assessment.review_state == ReviewState.PARTIAL_ACCEPTED
    assert assessment.review_comment == "En partie bien"
    assert assessment.reviewed_by == ddets_user
    assert assessment.review_institution == ddets

    # Check new infos
    response = client.get(info_url)
    assertContains(response, "En partie bien")
    assertContains(response, review_url)

    # Fix review
    response = client.get(review_url)
    assertContains(response, "En partie bien")
    response = client.post(
        review_url,
        data={
            "review_state": ReviewState.REMAINDER_REFUSED,
            "review_comment": "C'est refusé",
        },
    )
    assertRedirects(response, info_url)
    previous_reviewed_at = assessment.reviewed_at
    assessment.refresh_from_db()
    assert assessment.reviewed_at > previous_reviewed_at
    assert assessment.review_state == ReviewState.REMAINDER_REFUSED
    assert assessment.review_comment == "C'est refusé"
    assert assessment.reviewed_by == ddets_user
    assert assessment.review_institution == ddets


def test_employee_list_and_details(client, snapshot):
    geiq_membership = CompanyMembershipFactory(
        company__kind=CompanyKind.GEIQ,
        company__department="33",
        company__for_snapshot=True,
    )
    geiq_user = geiq_membership.user
    assessment = ImplementationAssessmentFactory(
        company=geiq_membership.company,
        campaign__year=2023,
    )
    dreets_membership = InstitutionMembershipFactory(
        institution__kind=InstitutionKind.DREETS_GEIQ,
        institution__department=assessment.company.department,
    )
    dreets_user = dreets_membership.user

    employee_list_urls = {
        info_type: reverse("geiq:employee_list", kwargs={"assessment_pk": assessment.pk, "info_type": info_type})
        for info_type in InfoType
    }

    def check_snapshots(user, url, selector_to_snapshot_name):
        client.force_login(user)
        response = client.get(url)
        for selector, snapshot_name in selector_to_snapshot_name.items():
            assert str(
                parse_response_to_soup(
                    response,
                    selector=selector,
                    replace_in_attr=[
                        (
                            "href",
                            f"/geiq/assessment/{assessment.pk}",
                            "/geiq/assessment/[PK of ImplementationAssessment]",
                        ),
                        (
                            "href",
                            f"/company/{geiq_membership.company.pk}/card",
                            "/company/[PK of Company]/card",
                        ),
                    ],
                )
            ) == snapshot(name=snapshot_name)

    for user in [geiq_user, dreets_user]:
        for info_type in employee_list_urls:
            check_snapshots(
                user,
                employee_list_urls[info_type],
                {
                    # Title differs between user types but not info_type, hence the same snapshot
                    "#main .s-title-02": f"employee list title for {user.kind}",
                    # Body differs between info_type but not user_kind
                    "#main .s-section": f"empty employee list body - {info_type}",
                },
            )

    EmployeeFactory(
        pk=1,
        assessment=assessment,
        title=Title.M,
        first_name="Jean",
        last_name="PIERRE",
        birthdate=datetime.date(2000, 1, 2),
        other_data={
            "qualification": {"libelle": "Sans qualification"},
            "adresse_ville": "",
            "is_bac_general": None,
            "prescripteur": {"libelle": "Cap Emploi"},
        },
        support_days_nb=10,
        allowance_amount=0,
    )
    EmployeeFactory(
        pk=2,
        assessment=assessment,
        title=Title.MME,
        first_name="Jacqueline",
        last_name="Snow",
        birthdate=datetime.date(1999, 3, 4),
        other_data={"qualification": {"libelle": "Niveau 3 (CAP, BEP)"}, "adresse_ville": "Saint-Brieuc"},
        support_days_nb=100,
        allowance_amount=0,
    )
    EmployeeFactory(
        pk=3,
        assessment=assessment,
        title=Title.M,
        first_name="Thomas",
        last_name="Lapotre",
        birthdate=datetime.date(1998, 4, 5),
        other_data={"qualification": {"libelle": "Niveau 5 ou + (Bac+2 ou +)"}},
        support_days_nb=100,
        allowance_amount=814,
    )
    EmployeeFactory(
        pk=4,
        assessment=assessment,
        title=Title.MME,
        first_name="Rachida",
        last_name="DIHINTRUC",
        birthdate=datetime.date(1997, 5, 6),
        support_days_nb=100,
        allowance_amount=1400,
    )

    # Check key indicators & personal information
    for user in [geiq_user, dreets_user]:
        check_snapshots(
            user,
            employee_list_urls[InfoType.PERSONAL_INFORMATION],
            {
                "#main .s-section .c-box:has(h2)": "key indicators",
                "#result_page": "personal information",
            },
        )

    for user in [geiq_user, dreets_user]:
        check_snapshots(
            user,
            reverse("geiq:employee_details", kwargs={"employee_pk": 1}),
            {"#main .s-section": "detailed info of Jean PIERRE"},
        )


def test_employee_list_sync(client, mocker, label_settings):
    geiq_membership = CompanyMembershipFactory(
        company__kind=CompanyKind.GEIQ,
        company__department="33",
        company__for_snapshot=True,
    )
    assessment = ImplementationAssessmentFactory(
        company=geiq_membership.company,
        campaign__year=2023,
    )
    assert assessment.last_synced_at is None

    def _fake_get_all_contracts(self, geiq_id):
        assert geiq_id == assessment.label_id
        return []

    def _fake_get_all_prequalifications(self, geiq_id):
        assert geiq_id == assessment.label_id
        return []

    mocker.patch.object(geiq_label.LabelApiClient, "get_all_contracts", _fake_get_all_contracts)
    mocker.patch.object(geiq_label.LabelApiClient, "get_all_prequalifications", _fake_get_all_prequalifications)

    client.force_login(geiq_membership.user)
    response = client.post(
        reverse("geiq:employee_list", kwargs={"assessment_pk": assessment.pk, "info_type": InfoType.CONTRACT})
    )
    assert response.status_code == 200
    assessment.refresh_from_db()
    assessment.last_synced_at is not None
