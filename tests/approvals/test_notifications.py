from itou.approvals import notifications

from ..users.factories import PrescriberFactory
from .factories import ProlongationRequestFactory


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
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestDeniedEmployer(prolongation_request).email

    assert email.to == [prolongation_request.declared_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_denied_jobseeker(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestDeniedJobSeeker(prolongation_request).email

    assert email.to == [prolongation_request.approval.user.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
