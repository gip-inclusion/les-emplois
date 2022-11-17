from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.approvals.factories import ApprovalFactory, SuspensionFactory
from itou.siaes.factories import SiaeFactory


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

        assertContains(response, "1 Résultat")
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

        assertContains(response, "2 Résultats")
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

        assertContains(response, "1 Résultat")

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
        response = client.get(url)
        assertContains(response, "2 Résultats")
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
        assertContains(response, "1 Résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": approval.pk}))
        assertNotContains(response, reverse("approvals:detail", kwargs={"pk": approval_same_siae.pk}))
        assertNotContains(response, reverse("approvals:detail", kwargs={"pk": approval_other_siae.pk}))

        url = f"{reverse('approvals:list')}?users={approval.user_id}&users={approval_same_siae.user_id}"
        response = client.get(url)
        assertContains(response, "2 Résultats")
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
        assertContains(response, "1 Résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": valid_approval.pk}))

        url = f"{reverse('approvals:list')}?status_suspended=on"
        response = client.get(url)
        assertContains(response, "1 Résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": suspended_approval.pk}))

        url = f"{reverse('approvals:list')}?status_future=on"
        response = client.get(url)
        assertContains(response, "1 Résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": future_approval.pk}))

        url = f"{reverse('approvals:list')}?status_expired=on"
        response = client.get(url)
        assertContains(response, "1 Résultat")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": expired_approval.pk}))

        url = f"{reverse('approvals:list')}?status_expired=on&status_suspended=on&status_future=on&status_valid=on"
        response = client.get(url)
        assertContains(response, "4 Résultats")
        assertContains(response, reverse("approvals:detail", kwargs={"pk": valid_approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": suspended_approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": future_approval.pk}))
        assertContains(response, reverse("approvals:detail", kwargs={"pk": expired_approval.pk}))

        assertContains(
            response,
            """<span class="badge badge-pill  badge-success  ">
                        <i class="ri-checkbox-circle-line"></i>
                        <span class="font-weight-normal">&nbsp;PASS IAE Valide</span>
                    </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-pill  badge-success  ">
                        <i class="ri-checkbox-circle-line"></i>
                        <span class="font-weight-normal">&nbsp;PASS IAE Valide (non démarré)</span>
                    </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-pill  badge-success  ">
                        <i class="ri-error-warning-line"></i>
                        <span class="font-weight-normal">&nbsp;PASS IAE Valide (suspendu)</span>
                    </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-pill  badge-dark  ">
                        <i class="ri-forbid-2-line"></i>
                        <span class="font-weight-normal">&nbsp;PASS IAE Expiré</span>
                    </span>""",
            html=True,
        )
