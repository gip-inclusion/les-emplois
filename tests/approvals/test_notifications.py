from itou.approvals import notifications

from .factories import ProlongationRequestDenyInformationFactory, ProlongationRequestFactory


def test_prolongation_request_created(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestCreatedForPrescriberNotification(
        prolongation_request.validated_by,
        prolongation_request.prescriber_organization,
        prolongation_request=prolongation_request,
    ).build()

    assert email.to == [prolongation_request.validated_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_created_reminder(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestCreatedReminderForPrescriberNotification(
        prolongation_request.validated_by,
        prolongation_request.prescriber_organization,
        prolongation_request=prolongation_request,
    ).build()

    assert email.to == [prolongation_request.validated_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_granted_employer(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestGrantedForEmployerNotification(
        prolongation_request.declared_by,
        prolongation_request.declared_by_siae,
        prolongation_request=prolongation_request,
    ).build()

    assert email.to == [prolongation_request.declared_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_granted_jobseeker(snapshot):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    email = notifications.ProlongationRequestGrantedForJobSeekerNotification(
        prolongation_request.approval.user,
        prolongation_request=prolongation_request,
    ).build()

    assert email.to == [prolongation_request.approval.user.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_denied_employer(snapshot):
    prolongation_request = ProlongationRequestDenyInformationFactory(for_snapshot=True).request
    email = notifications.ProlongationRequestDeniedForEmployerNotification(
        prolongation_request.declared_by,
        prolongation_request.declared_by_siae,
        prolongation_request=prolongation_request,
    ).build()

    assert email.to == [prolongation_request.declared_by.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")


def test_prolongation_request_denied_jobseeker(snapshot):
    prolongation_request = ProlongationRequestDenyInformationFactory(for_snapshot=True).request
    email = notifications.ProlongationRequestDeniedForJobSeekerNotification(
        prolongation_request.approval.user, prolongation_request=prolongation_request
    ).build()

    assert email.to == [prolongation_request.approval.user.email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
