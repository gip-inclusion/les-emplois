from functools import partial

import pytest
from freezegun import freeze_time

from itou.companies.models import CompanyMembership
from itou.insertion import notifications
from itou.insertion.enums import OrientationRefusalReason, OrientationStatus
from itou.job_applications.enums import SenderKind
from itou.prescribers.models import PrescriberMembership
from tests.companies.factories import CompanyMembershipFactory
from tests.insertion.factories import OrientationFactory, ProcessOrientationLinkFactory
from tests.prescribers.factories import PrescriberMembershipFactory


def test_new_orientation_for_structure(snapshot):
    link = ProcessOrientationLinkFactory(orientation__for_snapshot=True)
    email = link.email_orientation_new_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of ProcessOrientationLink]")
    assert body == snapshot(name="body")


@pytest.mark.parametrize(
    "contact_full_name,contact_phone",
    [("", ""), ("Jean Dupont", "0102030405")],
    ids=["minimum_contact_info", "maximum_contact_info"],
)
def test_new_orientation_for_referent(snapshot, contact_full_name, contact_phone):
    orientation = OrientationFactory(
        for_snapshot=True, service__contact_full_name=contact_full_name, service__contact_phone=contact_phone
    )
    email = orientation.email_orientation_new_for_referent

    assert email.to == [orientation.referent_email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@pytest.mark.parametrize(
    "membership_factory",
    [
        CompanyMembershipFactory,
        partial(PrescriberMembershipFactory, organization__authorized=True),
        PrescriberMembershipFactory,
    ],
    ids=["from_employer", "from_authorized_prescriber", "from_unauthorized_prescriber"],
)
def test_new_orientation_for_sender(snapshot, membership_factory):
    membership = membership_factory(user__first_name="Aline")
    sender_prescriber_organization = membership.organization if isinstance(membership, PrescriberMembership) else None
    sender_company = membership.company if isinstance(membership, CompanyMembership) else None
    sender_kind = SenderKind.PRESCRIBER if sender_prescriber_organization else SenderKind.EMPLOYER

    orientation = OrientationFactory(
        for_snapshot=True,
        sender_kind=sender_kind,
        sender=membership.user,
        sender_prescriber_organization=sender_prescriber_organization,
        sender_company=sender_company,
    )
    email = notifications.OrientationNewForSenderNotification(orientation.sender, orientation=orientation).build()

    assert email.to == [orientation.sender.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@pytest.mark.parametrize("sender_is_referent", [True, False], ids=["sender_is_referent", "sender_is_not_referent"])
def test_new_orientation_for_beneficiary(snapshot, sender_is_referent):
    orientation = OrientationFactory(for_snapshot=True)
    if sender_is_referent:
        orientation.referent_email = orientation.sender.email
        orientation.save()
    email = notifications.OrientationNewForBeneficiaryNotification(
        orientation.beneficiary, orientation=orientation
    ).build()

    assert email.to == [orientation.beneficiary.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_accepted_orientation_for_structure(snapshot):
    link = ProcessOrientationLinkFactory(orientation__for_snapshot=True)
    email = link.email_orientation_accepted_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of ProcessOrientationLink]")
    assert body == snapshot(name="body")


def test_accepted_orientation_for_referent(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = orientation.email_orientation_accepted_for_referent

    assert email.to == [orientation.referent_email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_accepted_orientation_for_sender(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = notifications.OrientationAcceptedForSenderNotification(orientation.sender, orientation=orientation).build()

    assert email.to == [orientation.sender.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_accepted_orientation_for_beneficiary(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = notifications.OrientationAcceptedForBeneficiaryNotification(
        orientation.beneficiary, orientation=orientation
    ).build()

    assert email.to == [orientation.beneficiary.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_refused_orientation_for_structure(snapshot):
    link = ProcessOrientationLinkFactory(
        orientation__for_snapshot=True,
        orientation__status=OrientationStatus.REFUSED,
        orientation__refusal_reasons=OrientationRefusalReason.values,
        orientation__refusal_details="Encore une autre raison personnalisée.",
    )
    email = link.email_orientation_refused_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of ProcessOrientationLink]")
    assert body == snapshot(name="body")


def test_refused_orientation_for_referent(snapshot):
    orientation = OrientationFactory(
        for_snapshot=True,
        status=OrientationStatus.REFUSED,
        refusal_reasons=OrientationRefusalReason.values,
        refusal_details="Encore une autre raison personnalisée.",
    )
    email = orientation.email_orientation_refused_for_referent

    assert email.to == [orientation.referent_email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@pytest.mark.parametrize(
    "membership_factory",
    [
        CompanyMembershipFactory,
        partial(PrescriberMembershipFactory, organization__authorized=True),
        PrescriberMembershipFactory,
    ],
    ids=["from_employer", "from_authorized_prescriber", "from_unauthorized_prescriber"],
)
def test_refused_orientation_for_sender(snapshot, membership_factory):
    membership = membership_factory()
    sender_prescriber_organization = membership.organization if isinstance(membership, PrescriberMembership) else None
    sender_company = membership.company if isinstance(membership, CompanyMembership) else None
    sender_kind = SenderKind.PRESCRIBER if sender_prescriber_organization else SenderKind.EMPLOYER

    orientation = OrientationFactory(
        for_snapshot=True,
        sender_kind=sender_kind,
        sender=membership.user,
        sender_prescriber_organization=sender_prescriber_organization,
        sender_company=sender_company,
        status=OrientationStatus.REFUSED,
        refusal_reasons=OrientationRefusalReason.values,
        refusal_details="Encore une autre raison personnalisée.",
    )
    email = notifications.OrientationRefusedForSenderNotification(orientation.sender, orientation=orientation).build()

    assert email.to == [orientation.sender.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_refused_orientation_for_beneficiary(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = notifications.OrientationRefusedForBeneficiaryNotification(
        orientation.beneficiary, orientation=orientation
    ).build()

    assert email.to == [orientation.beneficiary.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
