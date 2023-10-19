from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries, assertRedirects

from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import SiaeFactory
from tests.utils.test import BASE_NUM_QUERIES


class TestApprovalsListView:
    def test_anonymous_user(self, client):
        url = reverse("approvals:list")
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_list_view(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()

        approval_for_other_siae = ApprovalFactory(with_jobapplication=True)

        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "1 résultat")
        assertContains(response, approval.user.get_full_name())
        assertNotContains(response, approval_for_other_siae.user.get_full_name())
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval.pk}))

    def test_multiple_approvals_for_the_same_user(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()

        another_approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_siae=job_application.to_siae,
        )

        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "2 résultats")
        assertContains(response, approval.user.get_full_name(), count=2)
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": another_approval.pk}))

    def test_multiple_job_application(self, client):
        approval = ApprovalFactory(with_jobapplication=True)

        # Create another job_application on the same approval / siae
        job_application = approval.jobapplication_set.get()
        job_application.pk = None
        job_application.save()

        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "1 résultat")

    def test_users_filters(self, client):
        approval = ApprovalFactory(
            with_jobapplication=True,
            user__first_name="Jean",
            user__last_name="Vier",
        )
        job_application = approval.jobapplication_set.get()
        approval_same_siae = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_siae=job_application.to_siae,
            user__first_name="Seb",
            user__last_name="Tambre",
        )
        approval_other_siae = ApprovalFactory(with_jobapplication=True)

        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)

        url = reverse("approvals:list")
        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 2  # fetch siae memberships & its active/grace_period (middleware)
            + 1  # fetch job seekers (ApprovalForm._get_choices_for_job_seekers)
            + 1  # count (from paginator)
            + 1  # fetch approvals
            + 1  # check if in progress suspensions exist for each approval (Approval.is_suspended)
            + 3  # savepoint, update session, release savepoint
        ):
            response = client.get(url)
        assertContains(response, "2 résultats")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval_same_siae.pk}))
        assertNotContains(response, reverse("approvals:detail", kwargs={"pk": approval_other_siae.pk}))

        form = response.context["filters_form"]
        assert form.fields["users"].choices == [
            (approval.user_id, "Jean Vier"),
            (approval_same_siae.user_id, "Seb Tambre"),
        ]

        url = f"{reverse('approvals:list')}?users={approval.user_id}"
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval.pk}))
        assertNotContains(response, reverse("approvals:detail", kwargs={"pk": approval_same_siae.pk}))
        assertNotContains(response, reverse("approvals:detail", kwargs={"pk": approval_other_siae.pk}))

        url = f"{reverse('approvals:list')}?users={approval.user_id}&users={approval_same_siae.user_id}"
        response = client.get(url)
        assertContains(response, "2 résultats")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval_same_siae.pk}))
        assertNotContains(response, reverse("approvals:detail", kwargs={"pk": approval_other_siae.pk}))

    def test_approval_state_filters(self, client):
        now = timezone.localdate()
        siae = SiaeFactory(with_membership=True)

        expired_approval = ApprovalFactory(
            start_at=now - relativedelta(years=3),
            end_at=now - relativedelta(years=1),
            with_jobapplication=True,
            with_jobapplication__to_siae=siae,
        )
        future_approval = ApprovalFactory(
            start_at=now + relativedelta(days=1),
            with_jobapplication=True,
            with_jobapplication__to_siae=siae,
        )
        valid_approval = ApprovalFactory(
            start_at=now - relativedelta(years=1),
            with_jobapplication=True,
            with_jobapplication__to_siae=siae,
        )
        suspended_approval = ApprovalFactory(
            start_at=now - relativedelta(years=1),
            with_jobapplication=True,
            with_jobapplication__to_siae=siae,
        )
        SuspensionFactory(
            approval=suspended_approval,
            start_at=now - relativedelta(days=1),
            end_at=now + relativedelta(days=1),
        )

        siae_member = siae.members.first()
        client.force_login(siae_member)

        url = f"{reverse('approvals:list')}?status_valid=on"
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": valid_approval.pk}))

        url = f"{reverse('approvals:list')}?status_suspended=on"
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": suspended_approval.pk}))

        url = f"{reverse('approvals:list')}?status_future=on"
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": future_approval.pk}))

        url = f"{reverse('approvals:list')}?status_expired=on"
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": expired_approval.pk}))

        url = f"{reverse('approvals:list')}?status_expired=on&status_suspended=on&status_future=on&status_valid=on"
        response = client.get(url)
        assertContains(response, "4 résultats")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": valid_approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": suspended_approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": future_approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": expired_approval.pk}))

        assertContains(
            response,
            """<span class="badge badge-sm rounded-pill text-wrap bg-success-lighter text-success">
                <i class="ri-pass-valid-line ri-xl" aria-hidden="true"></i>
                PASS IAE valide
            </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-sm rounded-pill text-wrap bg-success-lighter text-success">
                <i class="ri-pass-valid-line ri-xl" aria-hidden="true"></i>
                PASS IAE valide (non démarré)
            </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-sm rounded-pill text-wrap bg-success-lighter text-success">
                <i class="ri-pass-pending-line ri-xl" aria-hidden="true"></i>
                PASS IAE valide (suspendu)
            </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-sm rounded-pill text-wrap bg-emploi-light text-primary">
                <i class="ri-pass-expired-line ri-xl" aria-hidden="true"></i>
                PASS IAE expiré
            </span>""",
            html=True,
        )
