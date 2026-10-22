from datetime import timedelta
from functools import partial

import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from itou.companies.models import CompanyMembership
from itou.insertion import notifications
from itou.insertion.enums import OrientationRefusalReason, OrientationStatus
from itou.insertion.models import Orientation
from itou.job_applications.enums import SenderKind
from itou.prescribers.models import PrescriberMembership
from itou.utils.brand import product_name
from tests.companies.factories import CompanyMembershipFactory
from tests.insertion.factories import MobilizationEmailFactory, OrientationFactory, OrientationProcessLinkFactory
from tests.prescribers.factories import PrescriberMembershipFactory


def test_new_orientation_for_structure(snapshot):
    link = OrientationProcessLinkFactory(orientation__for_snapshot=True)
    email = link.email_new_orientation_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of OrientationProcessLink]")
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
    email = orientation.email_new_orientation_for_referent

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
    email = notifications.NewOrientationForSender(orientation.sender, orientation=orientation).build()

    assert email.to == [orientation.sender.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@pytest.mark.parametrize("sender_is_referent", [True, False], ids=["sender_is_referent", "sender_is_not_referent"])
def test_new_orientation_for_beneficiary(snapshot, sender_is_referent):
    orientation = OrientationFactory(for_snapshot=True)
    if sender_is_referent:
        orientation.referent_email = orientation.sender.email
        orientation.save()
    email = notifications.NewOrientationForBeneficiary(orientation.beneficiary, orientation=orientation).build()

    assert email.to == [orientation.beneficiary.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_accepted_orientation_for_structure(snapshot):
    link = OrientationProcessLinkFactory(orientation__for_snapshot=True)
    email = link.email_accepted_orientation_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of OrientationProcessLink]")
    assert body == snapshot(name="body")


def test_accepted_orientation_for_referent(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = orientation.email_accepted_orientation_for_referent

    assert email.to == [orientation.referent_email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
@pytest.mark.parametrize(
    "membership_factory",
    [
        CompanyMembershipFactory,
        partial(PrescriberMembershipFactory, organization__authorized=True),
        PrescriberMembershipFactory,
    ],
    ids=["from_employer", "from_authorized_prescriber", "from_unauthorized_prescriber"],
)
def test_accepted_orientation_for_sender(membership_factory, snapshot):
    membership = membership_factory(user__first_name="Jeanne", user__for_snapshot=True)
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
    email = notifications.AcceptedOrientationForSender(orientation.sender, orientation=orientation).build()

    assert email.to == [orientation.sender.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_accepted_orientation_for_beneficiary(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = notifications.AcceptedOrientationForBeneficiary(orientation.beneficiary, orientation=orientation).build()

    assert email.to == [orientation.beneficiary.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_refused_orientation_for_structure(snapshot):
    link = OrientationProcessLinkFactory(
        orientation__for_snapshot=True,
        orientation__status=OrientationStatus.REFUSED,
        orientation__refusal_reasons=OrientationRefusalReason.values,
        orientation__refusal_details="Encore une autre raison personnalisée.",
    )
    email = link.email_refused_orientation_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of OrientationProcessLink]")
    assert body == snapshot(name="body")


def test_refused_orientation_for_referent(snapshot):
    orientation = OrientationFactory(
        for_snapshot=True,
        status=OrientationStatus.REFUSED,
        refusal_reasons=OrientationRefusalReason.values,
        refusal_details="Encore une autre raison personnalisée.",
    )
    email = orientation.email_refused_orientation_for_referent

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
    membership = membership_factory(user__for_snapshot=True)
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
    email = notifications.RefusedOrientationForSender(orientation.sender, orientation=orientation).build()

    assert email.to == [orientation.sender.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_refused_orientation_for_beneficiary(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = notifications.RefusedOrientationForBeneficiary(orientation.beneficiary, orientation=orientation).build()

    assert email.to == [orientation.beneficiary.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_expired_orientation_for_structure(snapshot):
    link = OrientationProcessLinkFactory(orientation__for_snapshot=True)
    email = link.email_expired_orientation_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of OrientationProcessLink]")
    assert body == snapshot(name="body")


def test_expired_orientation_for_referent(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = orientation.email_expired_orientation_for_referent

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
def test_expired_orientation_for_sender(snapshot, membership_factory):
    membership = membership_factory(user__for_snapshot=True)
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
    email = notifications.ExpiredOrientationForSender(orientation.sender, orientation=orientation).build()

    assert email.to == [orientation.sender.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


@freeze_time("2026-08-13")
def test_expired_orientation_for_beneficiary(snapshot):
    orientation = OrientationFactory(for_snapshot=True)
    email = notifications.ExpiredOrientationForBeneficiary(orientation.beneficiary, orientation=orientation).build()

    assert email.to == [orientation.beneficiary.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_orientation_new_link_for_structure(snapshot):
    link = OrientationProcessLinkFactory(orientation__for_snapshot=True)
    email = link.email_new_link_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of OrientationProcessLink]")
    assert body == snapshot(name="body")


@freeze_time("2026-08-13")
@pytest.mark.parametrize("reminder_days_multiplicator", [1, 2])
def test_orientation_reminder_for_structure(snapshot, reminder_days_multiplicator):
    with freeze_time(
        timezone.now() - timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS * reminder_days_multiplicator)
    ):
        orientation = OrientationFactory(for_snapshot=True)
    link = OrientationProcessLinkFactory(orientation=orientation)
    email = link.email_reminder_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of OrientationProcessLink]")
    assert body == snapshot(name="body")


def test_free_form_email_to_service(snapshot):
    mobilization_email = MobilizationEmailFactory(
        sender__for_snapshot=True, sender_prescriber_organization__for_snapshot=True
    )
    body_message = """Bonjour,

Je souhaiterais orienter un usager vers votre service "SERVICE".

Mon usager a 33 ans et habite à Vannes (56).




Plusieurs retours à la ligne non pris en compte.

Cordialement,
Pierre DUPONT"""
    email = mobilization_email.free_form_email_to_service(body_message)

    assert (
        str(email.from_email)
        == f"{mobilization_email.sender.get_full_name()} {product_name('via')} <{settings.DEFAULT_FROM_EMAIL}>"
    )
    assert email.to == [mobilization_email.service.contact_email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_free_form_email_to_sender(snapshot):
    mobilization_email = MobilizationEmailFactory(
        sender__for_snapshot=True,
        sender_prescriber_organization__for_snapshot=True,
    )
    from_email = "Jean DUSERVICE <jean@service.fake>"
    reply_to = "Jean DUSERVICE <jean@example.com>"
    body_message = """Bonjour,

Bien reçu.

Cordialement,
Jean DUSERVICE"""
    email = mobilization_email.free_form_email_to_sender(body_message, from_email, reply_to=reply_to)

    assert email.from_email == from_email
    assert email.to == [mobilization_email.sender.email]
    assert email.reply_to == [reply_to]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
