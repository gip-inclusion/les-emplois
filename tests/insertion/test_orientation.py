import pytest
from django.conf import settings
from django.db import IntegrityError

from itou.insertion.enums import BeneficiaryContactPreference, OrientationStatus
from itou.insertion.models import Orientation
from itou.job_applications.enums import SenderKind
from tests.companies.factories import CompanyFactory
from tests.insertion.factories import OrientationFactory, ServiceFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


def test_orientation_default_status():
    orientation = OrientationFactory()
    assert orientation.status == OrientationStatus.PENDING
    assert orientation.id is not None


def test_orientation_prescriber_sender_constraint():
    organization = PrescriberOrganizationFactory()
    orientation = OrientationFactory(
        sender=PrescriberFactory(),
        sender_kind=SenderKind.PRESCRIBER,
        sender_prescriber_organization=organization,
        sender_company=None,
    )
    assert orientation.sender_organization == organization


def test_orientation_employer_sender_constraint():
    company = CompanyFactory()
    orientation = OrientationFactory(
        sender=EmployerFactory(),
        sender_kind=SenderKind.EMPLOYER,
        sender_company=company,
        sender_prescriber_organization=None,
    )
    assert orientation.sender_organization == company


def test_orientation_rejects_inconsistent_sender_organization():
    with pytest.raises(IntegrityError):
        Orientation.objects.create(
            beneficiary=JobSeekerFactory(),
            sender=PrescriberFactory(),
            sender_kind=SenderKind.PRESCRIBER,
            sender_prescriber_organization=None,
            sender_company=None,
            service=ServiceFactory(),
            referent_first_name="Alice",
            referent_last_name="Martin",
            referent_email="alice@example.org",
        )


def test_orientation_attachments(temporary_dora_bucket_name):
    orientation = OrientationFactory(
        attachments=[
            "local/#orientations/7d6dnkQ2E4bz7slKI5mKOnJG1XPYQRtQ/document0.pdf",
            "local/#orientations/LuBBIUvx6idprXo6QjpYyHi4QsmcXTdS/document1.pdf",
        ]
    )

    for idx, attachment_detail in enumerate(orientation.attachments_details):
        assert attachment_detail[0] == f"document{idx}.pdf"
        assert settings.DORA_AWS_S3_ENDPOINT_URL in attachment_detail[1]
        assert temporary_dora_bucket_name in attachment_detail[1]


@pytest.mark.parametrize(
    "contact_preferences,other_contact_method,expected",
    [
        ([], "", ""),
        (
            [
                BeneficiaryContactPreference.PHONE,
                BeneficiaryContactPreference.EMAIL,
                BeneficiaryContactPreference.REFERENT,
            ],
            "",
            "téléphone, e-mail, via le conseiller référent",
        ),
        ([BeneficiaryContactPreference.EMAIL, BeneficiaryContactPreference.PHONE], "", "e-mail, téléphone"),
        (
            [BeneficiaryContactPreference.EMAIL, BeneficiaryContactPreference.OTHER],
            "par pigeon voyageur",
            "e-mail, autre (par pigeon voyageur)",
        ),
        ([BeneficiaryContactPreference.EMAIL], "par pigeon voyageur", "e-mail"),
        ([BeneficiaryContactPreference.EMAIL, BeneficiaryContactPreference.OTHER], "", "e-mail"),
    ],
)
def test_beneficiary_contact_preferences_display(contact_preferences, other_contact_method, expected):
    orientation = OrientationFactory(
        beneficiary_contact_preferences=contact_preferences, beneficiary_other_contact_method=other_contact_method
    )
    assert orientation.beneficiary_contact_preferences_display == expected
