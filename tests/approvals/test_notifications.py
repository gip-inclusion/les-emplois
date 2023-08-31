import datetime

from itou.approvals import notifications

from ..users.factories import PrescriberFactory
from .factories import ProlongationRequestDenyInformationFactory, ProlongationRequestFactory


def test_prolongation_request_created(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestCreated(prolongation_request).email

    assert email.to == [prolongation_request.validated_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_created_reminder(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    other_prescribers = PrescriberFactory.create_batch(
        3, membership__organization=prolongation_request.prescriber_organization
    )
    email = notifications.ProlongationRequestCreatedReminder(prolongation_request).email

    assert email.to == [prolongation_request.validated_by.email]
    assert set(email.cc) == {member.email for member in other_prescribers}
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_created_reminder_carbon_copy_list_limit():
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    prescribers = []
    for i in range(1, 12):
        prescribers.append(
            PrescriberFactory(
                membership__organization=prolongation_request.prescriber_organization,
                last_login=datetime.datetime(2000, 1, i, tzinfo=datetime.UTC),
            )
        )
    # We limit to the 10 most recent active users, so the first one created should not make the cut
    [_, *prescribers_to_be_cc] = prescribers
    PrescriberFactory(
        membership__organization=prolongation_request.prescriber_organization,
        last_login=None,
    )
    email = notifications.ProlongationRequestCreatedReminder(prolongation_request).email

    assert set(email.cc) == {member.email for member in prescribers_to_be_cc}


def test_prolongation_request_granted_employer(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestGrantedEmployer(prolongation_request).email

    assert email.to == [prolongation_request.declared_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_granted_jobseeker(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestGrantedJobSeeker(prolongation_request).email

    assert email.to == [prolongation_request.approval.user.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_denied_employer(snapshot):
    prolongation_request = ProlongationRequestDenyInformationFactory(for_snapshot=True).request
    email = notifications.ProlongationRequestDeniedEmployer(prolongation_request).email

    assert email.to == [prolongation_request.declared_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_denied_jobseeker(snapshot):
    prolongation_request = ProlongationRequestDenyInformationFactory(for_snapshot=True).request
    email = notifications.ProlongationRequestDeniedJobSeeker(prolongation_request).email

    assert email.to == [prolongation_request.approval.user.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
