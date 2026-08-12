import datetime
import random
from functools import partial

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from freezegun import freeze_time

from itou.companies.models import CompanyMembership
from itou.insertion.enums import (
    BeneficiaryContactPreference,
    OrientationRefusalReason,
    OrientationStatus,
    OrientationTransition,
)
from itou.insertion.models import Orientation, OrientationProcessLink, OrientationTransitionLog
from itou.job_applications.enums import SenderKind
from itou.prescribers.models import PrescriberMembership
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.insertion.factories import OrientationFactory, OrientationProcessLinkFactory, ServiceFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
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
    "sender_email,referent_email,expected_sender_is_referent",
    [
        ("sender@email.fake", "sender@email.fake", True),
        ("Sender_email+presScripteur12@email.fake", "sender_email+presscripteur12@email.fake", True),
        ("sender@email.fake", "referent@email.fake", False),
    ],
)
def test_sender_is_referent(sender_email, referent_email, expected_sender_is_referent):
    orientation = OrientationFactory(sender__email=sender_email, referent_email=referent_email)
    assert orientation.sender_is_referent == expected_sender_is_referent


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
        ([BeneficiaryContactPreference.EMAIL, BeneficiaryContactPreference.OTHER], "", "e-mail, autre"),
    ],
)
def test_beneficiary_contact_preferences_display(contact_preferences, other_contact_method, expected):
    orientation = OrientationFactory(
        beneficiary_contact_preferences=contact_preferences, beneficiary_other_contact_method=other_contact_method
    )
    assert orientation.beneficiary_contact_preferences_display == expected


@pytest.mark.django_db(transaction=True)
def test_refusal_consistency():
    with pytest.raises(IntegrityError, match=".*orientation_refusal_status_and_reasons_consistent.*"):
        OrientationFactory(status=OrientationStatus.REFUSED, refusal_reasons=[])
    with pytest.raises(IntegrityError, match=".*orientation_refusal_status_and_reasons_consistent.*"):
        OrientationFactory(
            status=random.choice(list(set(OrientationStatus.values) - {OrientationStatus.REFUSED.value})),
            refusal_reasons=[OrientationRefusalReason.DID_NOT_COME_TO_INTERVIEW],
        )
    assert not Orientation.objects.exists()


@pytest.mark.parametrize(
    "membership_factory,expected",
    [
        (CompanyMembershipFactory, True),
        (partial(PrescriberMembershipFactory, organization__authorized=True), True),
        (partial(PrescriberMembershipFactory, organization__authorized=False), False),
    ],
)
def test_sender_can_view_personal_information(membership_factory, expected):
    membership = membership_factory()
    sender_prescriber_organization = membership.organization if isinstance(membership, PrescriberMembership) else None
    sender_company = membership.company if isinstance(membership, CompanyMembership) else None
    sender_kind = SenderKind.PRESCRIBER if sender_prescriber_organization else SenderKind.EMPLOYER
    assert (
        OrientationFactory(
            sender_kind=sender_kind,
            sender=membership.user,
            sender_prescriber_organization=sender_prescriber_organization,
            sender_company=sender_company,
        ).sender_can_view_personal_information
        is expected
    )


def test_transition_process():
    orientation = OrientationFactory()
    timestamp = datetime.datetime(2026, 8, 6, 12, 0, tzinfo=datetime.UTC)
    with freeze_time(timestamp):
        orientation.process()

    log = OrientationTransitionLog.objects.get(
        orientation=orientation,
        transition=OrientationTransition.PROCESS,
        from_state=OrientationStatus.PENDING,
        to_state=OrientationStatus.PROCESSING,
        timestamp=timestamp,
    )
    assert log.orientation.status == OrientationStatus.PROCESSING
    assert log.orientation.updated_at == timestamp


@pytest.mark.parametrize("from_state", [OrientationStatus.PENDING, OrientationStatus.PROCESSING])
def test_transition_accept(from_state):
    orientation = OrientationFactory(status=from_state)
    timestamp = datetime.datetime(2026, 8, 6, 12, 0, tzinfo=datetime.UTC)
    with freeze_time(timestamp):
        orientation.accept()

    log = OrientationTransitionLog.objects.get(
        orientation=orientation,
        transition=OrientationTransition.ACCEPT,
        from_state=from_state,
        to_state=OrientationStatus.ACCEPTED,
        timestamp=timestamp,
    )
    assert log.orientation.status == OrientationStatus.ACCEPTED
    assert log.orientation.updated_at == timestamp


@pytest.mark.parametrize("from_state", [OrientationStatus.PENDING, OrientationStatus.PROCESSING])
def test_transition_refuse(from_state):
    orientation = OrientationFactory(status=from_state)
    timestamp = datetime.datetime(2026, 8, 6, 12, 0, tzinfo=datetime.UTC)
    with freeze_time(timestamp):
        with transaction.atomic():
            orientation.refusal_reasons = [OrientationRefusalReason.NOT_ELIGIBLE]
            orientation.refuse()

    log = OrientationTransitionLog.objects.get(
        orientation=orientation,
        transition=OrientationTransition.REFUSE,
        from_state=from_state,
        to_state=OrientationStatus.REFUSED,
        timestamp=timestamp,
    )
    assert log.orientation.status == OrientationStatus.REFUSED
    assert log.orientation.updated_at == timestamp


@pytest.mark.parametrize("from_state", [OrientationStatus.PENDING, OrientationStatus.PROCESSING])
def test_transition_expire(from_state):
    orientation = OrientationFactory(status=from_state)
    timestamp = datetime.datetime(2026, 8, 6, 12, 0, tzinfo=datetime.UTC)
    with freeze_time(timestamp):
        orientation.expire()

    log = OrientationTransitionLog.objects.get(
        orientation=orientation,
        transition=OrientationTransition.EXPIRE,
        from_state=from_state,
        to_state=OrientationStatus.EXPIRED,
        timestamp=timestamp,
    )
    assert log.orientation.status == OrientationStatus.EXPIRED
    assert log.orientation.updated_at == timestamp


def test_orientation_process_link_expiration():
    now = timezone.now()

    with freeze_time(now):
        process_link = OrientationProcessLinkFactory()
    assert process_link.is_valid

    with freeze_time(now + datetime.timedelta(seconds=OrientationProcessLink.MAX_VALIDTITY_SECONDS)):
        assert process_link.is_valid

    with freeze_time(now + datetime.timedelta(seconds=OrientationProcessLink.MAX_VALIDTITY_SECONDS + 1)):
        assert not process_link.is_valid
