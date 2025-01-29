import datetime

from dateutil.relativedelta import relativedelta
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.approvals.enums import (
    Origin,
    ProlongationReason,
    ProlongationRequestStatus,
)
from itou.approvals.models import Approval
from itou.job_applications.enums import JobApplicationState
from itou.utils.templatetags.format_filters import format_approval_number
from tests.approvals.factories import (
    ApprovalFactory,
    ProlongationFactory,
    ProlongationRequestFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory, LaborInspectorFactory
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup


class TestApprovalDetailView:
    def test_anonymous_user(self, client):
        approval = JobApplicationFactory(with_approval=True).approval
        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_wrong_user_type(self, client):
        approval = JobApplicationFactory(with_approval=True).approval
        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        user = LaborInspectorFactory(membership=True)
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 403

    def test_job_seeker_access(self, client):
        approval = JobApplicationFactory(with_approval=True).approval
        url = reverse("approvals:details", kwargs={"pk": approval.pk})

        user = JobSeekerFactory()
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 403

        client.force_login(approval.user)
        response = client.get(url)
        assert response.status_code == 200

    @freeze_time("2024-09-25")
    def test_approval_detail_box(self, client, snapshot):
        approval = ApprovalFactory(for_snapshot=True)
        job_application = JobApplicationFactory(
            to_company__name="Mon SIAE",
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            job_seeker=approval.user,
        )
        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        employer = job_application.to_company.members.first()
        prescriber = job_application.sender
        assert prescriber.is_prescriber
        job_seeker = approval.user

        # In progress
        for user in (job_seeker, employer, prescriber):
            client.force_login(user)
            response = client.get(url)
            approval_box = parse_response_to_soup(response, selector=".c-box--pass")
            assert str(approval_box) == snapshot(name="in progress approval from pe approval")

        # Tweak origin for following snapshots
        approval.origin = Origin.DEFAULT
        approval.save(update_fields=("origin",))

        # Suspended
        suspension = SuspensionFactory(
            id=1,
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=7),
            end_at=timezone.localdate() + relativedelta(days=3),
            siae__name="Une SIAE",
        )
        for user in (job_seeker, employer, prescriber):
            client.force_login(user)
            response = client.get(url)
            approval_box = parse_response_to_soup(response, selector=".c-box--pass")
            assert str(approval_box) == snapshot(name="suspended approval")
        suspension.delete()

        # Expired
        approval.end_at = approval.start_at + datetime.timedelta(days=1)
        approval.save(update_fields=("end_at",))
        for user in (job_seeker, employer, prescriber):
            client.force_login(user)
            response = client.get(url)
            approval_box = parse_response_to_soup(response, selector=".c-box--pass")
            assert str(approval_box) == snapshot(name="expired approval")

        # Future
        approval.start_at = datetime.date(2025, 1, 1)
        approval.end_at = datetime.date(2025, 1, 2)
        approval.save(update_fields=("start_at", "end_at"))
        for user in (job_seeker, employer, prescriber):
            client.force_login(user)
            response = client.get(url)
            approval_box = parse_response_to_soup(response, selector=".c-box--pass")
            assert str(approval_box) == snapshot(name="future approval")

    @freeze_time("2024-09-25", tick=True)  # tick is important for job applications' created_at
    def test_approval_detail_with_suspensions(self, client, snapshot):
        job_application = JobApplicationFactory(
            to_company__name="Mon SIAE",
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
        )
        approval = job_application.approval
        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        employer = job_application.to_company.members.first()
        prescriber = job_application.sender
        assert prescriber.is_prescriber

        # Valid
        current_suspension = SuspensionFactory(
            id=1,
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=7),
            end_at=timezone.localdate() + relativedelta(days=3),
            siae__name="Une SIAE",
        )
        # Older
        SuspensionFactory(
            id=2,
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=30),
            end_at=timezone.localdate() - relativedelta(days=20),
            siae__name="Une autre SIAE",
        )
        suspension_update_url = reverse("approvals:suspension_update", kwargs={"suspension_id": current_suspension.pk})
        suspension_delete_url = reverse(
            "approvals:suspension_action_choice", kwargs={"suspension_id": current_suspension.pk}
        )

        def get_suspensions_section(response):
            return parse_response_to_soup(
                response,
                selector=".s-section .row:nth-of-type(2) .c-box",
                replace_in_attr=[
                    ("href", f"/approvals/details/{approval.pk}", "/approvals/details/[PK of Approval]"),
                ],
            )

        client.force_login(employer)

        # As employer with modification rights
        with assertSnapshotQueries(snapshot(name="Approval detail view with suspensions as employer")):
            response = client.get(url)

        assertContains(response, suspension_update_url)
        assertContains(response, suspension_delete_url)

        assert str(get_suspensions_section(response)) == snapshot(
            name="Approval suspensions list as employer with modification buttons"
        )

        # As employer without modification rights: an other SIAE handles the approval now
        JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            job_seeker=job_application.job_seeker,
        )
        response = client.get(url)

        assertNotContains(response, suspension_update_url)
        assertNotContains(response, suspension_delete_url)
        assert str(get_suspensions_section(response)) == snapshot(
            name="Approval suspensions list as employer without modification buttons"
        )

        # As prescriber
        client.force_login(prescriber)
        with assertSnapshotQueries(snapshot(name="Approval detail view with suspensions as prescriber")):
            response = client.get(url)
        assertNotContains(response, suspension_update_url)
        assertNotContains(response, suspension_delete_url)

        assert str(get_suspensions_section(response)) == snapshot(
            name="Approval suspensions list as job_seeker/prescriber without modification buttons"
        )

        # As job_seeker
        client.force_login(approval.user)
        with assertSnapshotQueries(snapshot(name="Approval detail view with suspensions as job_seeker")):
            response = client.get(url)
        assertNotContains(response, suspension_update_url)
        assertNotContains(response, suspension_delete_url)

        assert str(get_suspensions_section(response)) == snapshot(
            name="Approval suspensions list as job_seeker/prescriber without modification buttons"
        )

    @freeze_time("2024-09-25", tick=True)  # tick is important for job applications' created_by
    def test_approval_detail_with_prolongations(self, client, snapshot):
        job_application = JobApplicationFactory(
            to_company__for_snapshot=True,
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
        )
        approval = job_application.approval
        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        employer = job_application.to_company.members.first()
        prescriber = job_application.sender
        assert prescriber.is_prescriber

        # Valid
        first = ProlongationFactory(
            id=1,
            approval=approval,
            start_at=approval.end_at,
            end_at=approval.end_at + datetime.timedelta(days=3),
            reason=ProlongationReason.RQTH.value,
            declared_by=employer,
            declared_by_siae=job_application.to_company,
            validated_by__first_name="Apou",
            validated_by__last_name="Vépar",
            validated_by__email="apou@vepar.fr",
            prescriber_organization=PrescriberOrganizationFactory(authorized=True, name="Une orga"),
            with_request=True,
        )
        # Older without request
        second = ProlongationFactory(
            id=2,
            approval=approval,
            start_at=first.end_at,
            end_at=first.end_at + datetime.timedelta(days=4),
            declared_by=employer,
            declared_by_siae=job_application.to_company,
            validated_by__first_name="Ack",
            validated_by__last_name="Cepté",
            validated_by__email="ack@cepte.fr",
        )
        ProlongationRequestFactory(
            approval=approval,
            status=ProlongationRequestStatus.DENIED,
            start_at=second.end_at,
            end_at=second.end_at + datetime.timedelta(days=5),
            reason=ProlongationReason.SENIOR_CDI.value,
            validated_by=None,
            declared_by=employer,
            declared_by_siae=None,  # A declaration user without SIAE
        )
        ProlongationRequestFactory(
            approval=approval,
            status=ProlongationRequestStatus.PENDING,
            start_at=second.end_at,
            end_at=second.end_at + datetime.timedelta(days=6),
            reason=ProlongationReason.SENIOR.value,
            declared_by=None,
            declared_by_siae=job_application.to_company,  # A declaration SIAE without user
            validated_by__first_name="Val",
            validated_by__last_name="Idépar",
            validated_by__email="val@idepar.fr",
        )

        def get_prolongations_section(response):
            return parse_response_to_soup(
                response,
                selector=".s-section .row:nth-of-type(3) .c-box",
                replace_in_attr=[
                    ("href", f"/approvals/details/{approval.pk}", "/approvals/details/[PK of Approval]"),
                ],
            )

        client.force_login(employer)

        # As employer with modification rights
        with assertSnapshotQueries(snapshot(name="Approval detail view with prolongations as employer")):
            response = client.get(url)

        assert str(get_prolongations_section(response)) == snapshot(name="Approval prolongations list as employer")

        # As prescriber
        client.force_login(prescriber)
        with assertSnapshotQueries(snapshot(name="Approval detail view with prolongations as prescriber")):
            response = client.get(url)

        assert str(get_prolongations_section(response)) == snapshot(
            name="Approval prolongations list as job_seeker/prescriber"
        )

        # As job_seeker
        client.force_login(approval.user)
        with assertSnapshotQueries(snapshot(name="Approval detail view with prolongations as job_seeker")):
            response = client.get(url)

        assert str(get_prolongations_section(response)) == snapshot(
            name="Approval prolongations list as job_seeker/prescriber"
        )

    def test_prolongation_button(self, client):
        TOO_SOON = (
            "Les prolongations ne sont possibles qu’entre le 7ème mois avant la "
            "fin d’un PASS IAE et jusqu’à son dernier jour de validité."
        )
        REQUEST_PENDING = "Il ne peut y avoir qu’une seule demande de prolongation en attente à la fois."
        TOO_LATE = "Il est impossible de faire une prolongation de PASS IAE expiré."

        job_application = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
        )
        approval = job_application.approval
        siae = job_application.to_company
        employer = siae.members.first()
        prescriber = job_application.sender
        assert prescriber.is_prescriber
        job_seeker = approval.user

        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        prolongation_url = reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id})

        def check_prolongation_url_and_reason(as_user, with_url, expected_reason):
            client.force_login(as_user)
            response = client.get(url)
            url_assert = assertContains if with_url else assertNotContains
            url_assert(response, prolongation_url)
            for reason in (TOO_SOON, REQUEST_PENDING, TOO_LATE):
                reason_assert = assertContains if reason == expected_reason else assertNotContains
                reason_assert(response, reason)

        # Too soon: impossible to prolong
        assert not approval.can_be_prolonged
        check_prolongation_url_and_reason(job_seeker, with_url=False, expected_reason=None)
        check_prolongation_url_and_reason(employer, with_url=False, expected_reason=TOO_SOON)
        check_prolongation_url_and_reason(prescriber, with_url=False, expected_reason=None)

        # Right before the end: prolongation is possible for employer
        with freeze_time(approval.end_at - datetime.timedelta(days=1)):
            approval = Approval.objects.get(pk=approval.pk)  # Reset cached properties
            assert approval.can_be_prolonged
            check_prolongation_url_and_reason(job_seeker, with_url=False, expected_reason=None)
            check_prolongation_url_and_reason(employer, with_url=True, expected_reason=None)
            check_prolongation_url_and_reason(prescriber, with_url=False, expected_reason=None)

            # With a pending prolongation request: impossible to prolong
            ProlongationRequestFactory(approval=approval)
            approval = Approval.objects.get(pk=approval.pk)  # Reset cached properties
            assert not approval.can_be_prolonged
            check_prolongation_url_and_reason(job_seeker, with_url=False, expected_reason=None)
            check_prolongation_url_and_reason(employer, with_url=False, expected_reason=REQUEST_PENDING)
            check_prolongation_url_and_reason(prescriber, with_url=False, expected_reason=None)

        # Too late: the approval has expired
        with freeze_time(approval.end_at + datetime.timedelta(days=1)):
            approval = Approval.objects.get(pk=approval.pk)  # Reset cached properties
            assert not approval.can_be_prolonged
            check_prolongation_url_and_reason(job_seeker, with_url=False, expected_reason=None)
            check_prolongation_url_and_reason(employer, with_url=False, expected_reason=TOO_LATE)
            check_prolongation_url_and_reason(prescriber, with_url=False, expected_reason=None)

    @freeze_time("2023-04-26")
    @override_settings(TALLY_URL="https://tally.so")
    def test_remove_approval_button(self, client, snapshot):
        REMOVAL_BUTTON_ID = "approval-deletion-link"
        membership = CompanyMembershipFactory(
            user__id=123456,
            user__email="oph@dewinter.com",
            user__first_name="Milady",
            user__last_name="de Winter",
            company__id=999999,
            company__name="ACI de la Rochelle",
        )
        job_application = JobApplicationFactory(
            hiring_start_at=datetime.date(2021, 3, 1),
            to_company=membership.company,
            job_seeker=JobSeekerFactory(last_name="John", first_name="Doe"),
            with_approval=True,
            # Don't set an ASP_ITOU_PREFIX (see approval.save for details)
            approval__number="XXXXX1234568",
        )
        # Create another accepted application lacking a proper hiring_start_at (like most old applications):
        # it should not impact the button display, and it should not crash
        JobApplicationFactory(
            hiring_start_at=None,
            to_company=membership.company,
            job_seeker=job_application.job_seeker,
            # Don't set an ASP_ITOU_PREFIX (see approval.save for details)
            approval=job_application.approval,
            state=JobApplicationState.ACCEPTED,
        )

        client.force_login(membership.user)

        # suspension still active, more than 1 year old, starting after the accepted job application
        suspension = SuspensionFactory(approval=job_application.approval, start_at=datetime.date(2022, 4, 8))
        url = reverse("approvals:details", kwargs={"pk": job_application.approval.pk})
        response = client.get(url)

        delete_button = parse_response_to_soup(response, selector=f"#{REMOVAL_BUTTON_ID}")
        assert str(delete_button) == snapshot(name="bouton de suppression d'un PASS IAE")

        # suspension now is inactive
        suspension.end_at = datetime.date(2023, 4, 10)  # more than 12 months but ended
        suspension.save(update_fields=["end_at"])
        response = client.get(url)

        delete_button = parse_response_to_soup(response, selector=f"#{REMOVAL_BUTTON_ID}")
        assert str(delete_button) == snapshot(name="bouton de suppression d'un PASS IAE")

        # An accepted job application exists after suspension end
        JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            job_seeker=job_application.job_seeker,
            approval=job_application.approval,
            hiring_start_at=suspension.end_at + datetime.timedelta(days=2),
        )
        response = client.get(url)
        assertNotContains(response, REMOVAL_BUTTON_ID)

    def test_suspend_button(self, client):
        ALREADY_SUSPENDED = "La suspension n’est pas possible car une suspension est déjà en cours."
        NOT_STARTED = "La suspension n’est pas possible car le PASS IAE n’a pas encore démarré."
        HANDLED_BY_OTHER_SIAE = "La suspension n’est pas possible car un autre employeur a embauché le candidat."
        EXPIRED = "Il est impossible de faire une suspension de PASS IAE expiré."

        job_application = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
        )
        approval = job_application.approval
        siae = job_application.to_company
        employer = siae.members.first()
        prescriber = job_application.sender
        assert prescriber.is_prescriber
        job_seeker = approval.user

        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        suspend_url = reverse("approvals:suspend", kwargs={"approval_id": approval.id})

        def check_suspend_url_and_reason(as_user, with_url, expected_reason):
            client.force_login(as_user)
            response = client.get(url)
            url_assert = assertContains if with_url else assertNotContains
            url_assert(response, suspend_url)
            for reason in (ALREADY_SUSPENDED, EXPIRED, HANDLED_BY_OTHER_SIAE, NOT_STARTED):
                reason_assert = assertContains if reason == expected_reason else assertNotContains
                reason_assert(response, reason)

        # Approval starting in the future
        with freeze_time(timezone.now() - datetime.timedelta(days=1)):
            assert not approval.is_in_progress
            assert not approval.can_be_suspended_by_siae(siae)
            check_suspend_url_and_reason(job_seeker, with_url=False, expected_reason=None)
            check_suspend_url_and_reason(employer, with_url=False, expected_reason=NOT_STARTED)
            check_suspend_url_and_reason(prescriber, with_url=False, expected_reason=None)

        # Back to an approval starting today that can be suspended
        approval = Approval.objects.get(pk=approval.pk)  # Reset cached properties
        assert approval.can_be_suspended_by_siae(siae)
        check_suspend_url_and_reason(job_seeker, with_url=False, expected_reason=None)
        check_suspend_url_and_reason(employer, with_url=True, expected_reason=None)
        check_suspend_url_and_reason(prescriber, with_url=False, expected_reason=None)

        # Suspended approval
        suspension = SuspensionFactory(
            approval=approval,
            start_at=timezone.localdate(),
            end_at=timezone.localdate() + relativedelta(days=1),
        )
        approval = Approval.objects.get(pk=approval.pk)  # Reset cached properties
        assert not approval.can_be_suspended_by_siae(siae)
        check_suspend_url_and_reason(job_seeker, with_url=False, expected_reason=None)
        check_suspend_url_and_reason(employer, with_url=False, expected_reason=ALREADY_SUSPENDED)
        check_suspend_url_and_reason(prescriber, with_url=False, expected_reason=None)

        suspension.delete()
        approval = Approval.objects.get(pk=approval.pk)  # Reset cached properties

        # New accepted job application: the approval is now handled by an other SIAE
        JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            job_seeker=job_application.job_seeker,
        )
        assert not approval.can_be_suspended_by_siae(siae)
        check_suspend_url_and_reason(job_seeker, with_url=False, expected_reason=None)
        check_suspend_url_and_reason(employer, with_url=False, expected_reason=HANDLED_BY_OTHER_SIAE)
        check_suspend_url_and_reason(prescriber, with_url=False, expected_reason=None)

        # Expired approval
        with freeze_time(approval.end_at + datetime.timedelta(days=1)):
            approval = Approval.objects.get(pk=approval.pk)  # Reset cached properties
            assert not approval.is_in_progress
            assert not approval.can_be_suspended_by_siae(siae)
            check_suspend_url_and_reason(job_seeker, with_url=False, expected_reason=None)
            check_suspend_url_and_reason(employer, with_url=False, expected_reason=EXPIRED)
            check_suspend_url_and_reason(prescriber, with_url=False, expected_reason=None)

    def test_employer_access(self, client):
        job_application = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
        )
        approval = job_application.approval
        siae = job_application.to_company
        url = reverse("approvals:details", kwargs={"pk": approval.pk})
        client.force_login(siae.members.first())

        PROLONG_BUTTON_LABEL = "<span>Prolonger</span>"
        SUSPEND_BUTTON_LABEL = "<span>Suspendre</span>"

        # Accepted job applications: employer has access with visible buttons
        response = client.get(url)
        assertContains(response, format_approval_number(job_application.approval.number))
        assertContains(response, PROLONG_BUTTON_LABEL, html=True)
        assertContains(response, SUSPEND_BUTTON_LABEL, html=True)

        # No accepted job application, but still a job application
        job_application.state = JobApplicationState.REFUSED
        job_application.save(update_fields=("state",))
        response = client.get(url)
        assertContains(response, format_approval_number(job_application.approval.number))
        assertNotContains(response, PROLONG_BUTTON_LABEL, html=True)
        assertNotContains(response, SUSPEND_BUTTON_LABEL, html=True)

        # No job application: no access
        job_application.delete()
        response = client.get(url)
        assert response.status_code == 403
