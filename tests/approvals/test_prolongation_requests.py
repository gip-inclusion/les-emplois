import contextlib
import itertools

import pytest
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.management.commands import prolongation_requests_chores
from itou.approvals.models import ProlongationRequest
from tests.approvals.factories import ProlongationRequestDenyInformationFactory, ProlongationRequestFactory
from tests.users.factories import EmployerFactory, PrescriberFactory


@pytest.fixture(name="command")
def command_fixture():
    return prolongation_requests_chores.Command()


def test_unique_approval_for_pending_constraint():
    prolongation_request = ProlongationRequestFactory(status=ProlongationRequestStatus.PENDING)

    with pytest.raises(IntegrityError, match="unique_prolongationrequest_approval_for_pending"):
        ProlongationRequest(
            approval=prolongation_request.approval,
            status=ProlongationRequestStatus.PENDING,
            assigned_to=prolongation_request.assigned_to,
        ).save()


def test_non_empty_proposed_actions_constraint():
    with pytest.raises(IntegrityError, match="non_empty_proposed_actions"):
        ProlongationRequestDenyInformationFactory(proposed_actions=[])


@pytest.mark.parametrize(
    "email,phone,expected",
    [
        ("email", "phone", contextlib.nullcontext()),
        ("email", "", pytest.raises(IntegrityError, match="check_prolongationrequest_require_phone_interview")),
        ("", "phone", pytest.raises(IntegrityError, match="check_prolongationrequest_require_phone_interview")),
        ("", "", pytest.raises(IntegrityError, match="check_prolongationrequest_require_phone_interview")),
    ],
)
def test_check_require_phone_interview_constraint(email, phone, expected):
    with expected:
        ProlongationRequestFactory(require_phone_interview=True, contact_email=email, contact_phone=phone)


@freeze_time()
def test_grant():
    prolongation_request = ProlongationRequestFactory()

    new_prolongation = prolongation_request.grant(prolongation_request.assigned_to)

    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.GRANTED
    assert prolongation_request.processed_by == prolongation_request.assigned_to
    assert prolongation_request.processed_at == timezone.now()
    assert prolongation_request.updated_by == prolongation_request.assigned_to
    assert list(prolongation_request.approval.prolongation_set.all()) == [new_prolongation]


@freeze_time()
@pytest.mark.parametrize("postcode,contained", [("59284", True), ("75001", False)])
def test_deny(django_capture_on_commit_callbacks, mailoutbox, postcode, contained):
    prolongation_request = ProlongationRequestFactory(approval__user__jobseeker_profile__hexa_post_code=postcode)
    deny_information = ProlongationRequestDenyInformationFactory.build(request=None)

    with django_capture_on_commit_callbacks(execute=True):
        prolongation_request.deny(prolongation_request.assigned_to, deny_information)

    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.DENIED
    assert prolongation_request.processed_by == prolongation_request.assigned_to
    assert prolongation_request.processed_at == timezone.now()
    assert prolongation_request.updated_by == prolongation_request.assigned_to
    assert prolongation_request.approval.prolongation_set.count() == 0
    assert prolongation_request.deny_information.reason == deny_information.reason
    assert prolongation_request.deny_information.reason_explanation == deny_information.reason_explanation
    assert prolongation_request.deny_information.proposed_actions == deny_information.proposed_actions
    assert (
        prolongation_request.deny_information.proposed_actions_explanation
        == deny_information.proposed_actions_explanation
    )
    assert [email.to for email in mailoutbox] == [
        [prolongation_request.declared_by.email],
        [prolongation_request.approval.user.email],
    ]
    jobseeker_email = mailoutbox[1]
    afpa = "Afpa"
    if contained:
        assert afpa in jobseeker_email.body
    else:
        assert afpa not in jobseeker_email.body


@pytest.mark.parametrize(
    "wet_run,expected",
    [
        (True, 2),  # Created more than 7 days ago, and without reminder_sent_at
        (False, 0),
    ],
)
def test_chores_send_reminder_to_prescriber_organization_other_members(
    snapshot, mailoutbox, caplog, command, django_capture_on_commit_callbacks, wet_run, expected
):
    parameters = itertools.product(
        ProlongationRequestStatus,
        [
            timezone.now() - relativedelta(days=11),  # Check we catch up missed run
            timezone.now() - relativedelta(days=10),  # On the day
            timezone.now() - relativedelta(days=9),  # Not before
        ],
        [None, timezone.now()],
    )
    for status, created_at, reminder_sent_at in parameters:
        ProlongationRequestFactory(status=status, created_at=created_at, reminder_sent_at=reminder_sent_at)

    with freeze_time():
        with django_capture_on_commit_callbacks(execute=True):
            command.handle(command="email_reminder", wet_run=wet_run)
        assert len(mailoutbox) == expected
        assert ProlongationRequest.objects.filter(reminder_sent_at=timezone.now()).count() == expected
    assert caplog.messages == snapshot()


def test_chores_send_reminder_to_prescriber_organization_other_members_every_ten_days_for_thirty_days(
    mailoutbox, django_capture_on_commit_callbacks, command
):
    prolongation_request = ProlongationRequestFactory()

    specs = [
        (0, 0),
        (9, 0),
        (10, 1),
        (11, 1),
        (19, 1),
        (20, 2),
        (21, 2),
        (29, 2),
        (30, 3),
        (31, 3),
        (40, 3),
    ]
    for days_ago, expected in specs:
        with freeze_time(prolongation_request.created_at + relativedelta(days=days_ago)):
            with django_capture_on_commit_callbacks(execute=True):
                command.handle(command="email_reminder", wet_run=True)
        assert len(mailoutbox) == expected


def test_chores_send_reminder_to_prescriber_organization_other_members_copy_limit(
    mailoutbox, snapshot, django_capture_on_commit_callbacks, command
):
    prolongation_request = ProlongationRequestFactory(for_snapshot=True)
    admin_prescribers = PrescriberFactory.create_batch(
        9, membership__organization=prolongation_request.prescriber_organization, membership__is_admin=True
    )
    regular_prescribers = PrescriberFactory.create_batch(
        3, membership__organization=prolongation_request.prescriber_organization, membership__is_admin=False
    )

    with freeze_time(prolongation_request.created_at + relativedelta(days=30)):
        with django_capture_on_commit_callbacks(execute=True):
            command.handle(command="email_reminder", wet_run=True)

    assert len(mailoutbox) == 11  # prolongation_request.assigned_to and 10 coworkers

    assert set(email.to[0] for email in mailoutbox) == {prolongation_request.assigned_to.email} | {
        member.email for member in admin_prescribers
    } | {regular_prescribers[-1].email}
    for email in mailoutbox:
        assert email.subject == snapshot(name="subject")
        assert email.body == snapshot(name="body")


def test_clean_declared_by_coherence():
    prolongation_request = ProlongationRequestFactory()
    prolongation_request.clean()

    employer = EmployerFactory()
    prolongation_request.declared_by = employer
    with pytest.raises(ValidationError) as error:
        prolongation_request.clean()
    assert error.match(
        "Le déclarant doit être un membre de la SIAE du déclarant. "
        f"Déclarant: {employer.id}, SIAE: {prolongation_request.declared_by_siae_id}."
    )
