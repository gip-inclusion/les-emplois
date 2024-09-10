import datetime

from dateutil.relativedelta import relativedelta
from django.template.defaultfilters import urlencode
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries, assertRedirects

from itou.www.approvals_views.views import ApprovalListView
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assert_previous_step, parse_response_to_soup


class TestApprovalsListView:
    def test_anonymous_user(self, client):
        url = reverse("approvals:list")
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_list_view(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()

        approval_for_other_company = ApprovalFactory(with_jobapplication=True)

        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "1 résultat")
        assertContains(response, approval.user.get_full_name())
        assertNotContains(response, approval_for_other_company.user.get_full_name())

        assert_previous_step(response, reverse("dashboard:index"))

        employee_base_url = reverse("employees:detail", kwargs={"public_id": approval.user.public_id})
        assertContains(response, f"{employee_base_url}?back_url={urlencode(url)}")

    def test_multiple_approvals_for_the_same_user(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()

        another_approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=job_application.to_company,
        )

        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "2 résultats")
        assertContains(response, f"<h3>{approval.user.get_full_name()}</h3>", html=True, count=1)
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": another_approval.user.public_id}))

    def test_multiple_job_application(self, client):
        approval = ApprovalFactory(with_jobapplication=True)

        # Create another job_application on the same approval / siae
        job_application = approval.jobapplication_set.get()
        job_application.pk = None
        job_application.save()

        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "1 résultat")

    def test_job_seeker_filters(self, client):
        approval = ApprovalFactory(
            with_jobapplication=True,
            user__first_name="Jean",
            user__last_name="Vier",
        )
        job_application = approval.jobapplication_set.get()
        approval_same_company = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=job_application.to_company,
            user__first_name="Seb",
            user__last_name="Tambre",
        )
        approval_other_company = ApprovalFactory(with_jobapplication=True)

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("approvals:list")
        # 1.  SELECT django_session
        # 2.  SELECT users_user
        # 3.  SELECT companies_companymembership
        # 4.  SELECT companies_company
        # END of middlewares
        # 5.  SAVEPOINT
        # 6.  SELECT users_user (job seekers with an accepted job app)
        # 7.  SELECT COUNT approvals_approval (paginator)
        # 8.  RELEASE SAVEPOINT
        # 9.  SELECT companies_siaeconvention (menu check for financial annexes)
        # 10. SELECT EXISTS users_user (menu check for active admin)
        # 11. SELECT DISTINCT approvals_approval
        # 12. SELECT approvals_suspension
        # 13. SAVEPOINT
        # 14. UPDATE django_session
        # 15. RELEASE SAVEPOINT
        with assertNumQueries(15):
            response = client.get(url)
        assertContains(response, "2 résultats")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
        assertContains(
            response, reverse("employees:detail", kwargs={"public_id": approval_same_company.user.public_id})
        )
        assertNotContains(
            response, reverse("employees:detail", kwargs={"public_id": approval_other_company.user.public_id})
        )

        form = response.context["filters_form"]
        assert form.fields["job_seeker"].choices == [
            (approval.user_id, "Jean VIER"),
            (approval_same_company.user_id, "Seb TAMBRE"),
        ]

        url = f"{reverse('approvals:list')}?job_seeker={approval.user_id}&expiry="
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
        assertNotContains(
            response, reverse("employees:detail", kwargs={"public_id": approval_same_company.user.public_id})
        )
        assertNotContains(
            response, reverse("employees:detail", kwargs={"public_id": approval_other_company.user.public_id})
        )

    def test_approval_state_filters(self, client):
        now = timezone.localdate()
        company = CompanyFactory(with_membership=True)

        expired_approval = ApprovalFactory(
            start_at=now - datetime.timedelta(days=3 * 365),
            end_at=now - datetime.timedelta(days=365),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        future_approval = ApprovalFactory(
            start_at=now + datetime.timedelta(days=1),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        valid_approval = ApprovalFactory(
            start_at=now - datetime.timedelta(days=365),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        suspended_approval = ApprovalFactory(
            start_at=now - datetime.timedelta(days=365),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        SuspensionFactory(
            approval=suspended_approval,
            start_at=now - datetime.timedelta(days=1),
            end_at=now + datetime.timedelta(days=1),
        )
        # Add 2 suspensions on valid approval because it used to cause duplicates
        # when valid and suspended filters were selected
        SuspensionFactory(
            approval=valid_approval,
            start_at=now - datetime.timedelta(days=10),
            end_at=now - datetime.timedelta(days=9),
        )
        SuspensionFactory(
            approval=valid_approval,
            start_at=now - datetime.timedelta(days=3),
            end_at=now - datetime.timedelta(days=2),
        )

        employer = company.members.first()
        client.force_login(employer)
        list_url = reverse("approvals:list")

        url = f"{list_url}?status_valid=on&expiry="
        response = client.get(url)
        print(response.content.decode())
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": valid_approval.user.public_id}))

        url = f"{list_url}?status_suspended=on&expiry="
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": suspended_approval.user.public_id}))

        url = f"{list_url}?status_future=on&expiry="
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": future_approval.user.public_id}))

        url = f"{list_url}?status_expired=on&expiry="
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": expired_approval.user.public_id}))

        url = f"{list_url}?status_expired=on&status_suspended=on&status_future=on&status_valid=on&expiry="
        response = client.get(url)
        assertContains(response, "4 résultats")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": valid_approval.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": suspended_approval.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": future_approval.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": expired_approval.user.public_id}))

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

        # Check IAE pass remainder days
        # Don't check human readable display as it's already done in another test and requires to freeze the date
        assertContains(response, "367 jours")
        assertContains(response, "365 jours")
        assertContains(response, "730 jours")
        assertContains(response, "0 jour")

    def test_approval_expiry_filters(self, client):
        now = timezone.localdate()
        company = CompanyFactory(with_membership=True)

        in_less_than_1_month = now + relativedelta(days=20)
        approval_1 = ApprovalFactory(
            start_at=in_less_than_1_month - relativedelta(years=2),
            end_at=in_less_than_1_month,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        in_less_than_3_months = now + relativedelta(days=80)
        approval_3 = ApprovalFactory(
            start_at=in_less_than_3_months - relativedelta(years=2),
            end_at=in_less_than_3_months,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        in_less_than_7_mmonths = now + relativedelta(days=200)
        approval_7 = ApprovalFactory(
            start_at=in_less_than_7_mmonths - relativedelta(years=2),
            end_at=in_less_than_7_mmonths,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        ApprovalFactory(
            start_at=now - relativedelta(years=1),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )

        employer = company.members.first()
        client.force_login(employer)

        url = f"{reverse('approvals:list')}?expiry=7"
        response = client.get(url)
        assertContains(response, "3 résultats")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_7.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_3.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_1.user.public_id}))

        url = f"{reverse('approvals:list')}?expiry=3"
        response = client.get(url)
        assertContains(response, "2 résultats")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_3.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_1.user.public_id}))

        url = f"{reverse('approvals:list')}?expiry=1"
        response = client.get(url)
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_1.user.public_id}))

        url = f"{reverse('approvals:list')}?expiry=7&status_expired=on"
        response = client.get(url)
        assertContains(response, "0 résultat")

    def test_approval_expiry_filter_default(self, client):
        company = CompanyFactory(with_membership=True)
        # Make sure we have access to page 2
        ApprovalFactory.create_batch(
            ApprovalListView.paginate_by + 1,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        employer = company.members.first()
        client.force_login(employer)

        list_url = reverse("approvals:list")
        response = client.get(list_url)
        # Check that the default "Fin du parcours en IAE" value "Tous" is selected
        expiry_all_input = parse_response_to_soup(response, "input[name='expiry'][value='']")
        assert expiry_all_input.has_attr("checked")
        response = client.get(f"{list_url}?page=2")
        # Check that the default "Fin du parcours en IAE" value "Tous" is selected
        expiry_all_input = parse_response_to_soup(response, "input[name='expiry'][value='']")
        assert expiry_all_input.has_attr("checked")

    def test_update_with_htmx(self, client):
        now = timezone.localdate()
        company = CompanyFactory(with_membership=True)

        in_less_than_1_month = now + relativedelta(days=20)
        approval_1 = ApprovalFactory(
            start_at=in_less_than_1_month - relativedelta(years=2),
            end_at=in_less_than_1_month,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        in_less_than_3_months = now + relativedelta(days=80)
        approval_3 = ApprovalFactory(
            start_at=in_less_than_3_months - relativedelta(years=2),
            end_at=in_less_than_3_months,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        employer = company.members.first()
        client.force_login(employer)

        url = f"{reverse('approvals:list')}"
        response = client.get(url, {"expiry": "3"})
        assertContains(response, "2 résultats")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_3.user.public_id}))
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval_1.user.public_id}))
        simulated_page = parse_response_to_soup(response)

        [less_than_3_months] = simulated_page.find_all("input", attrs={"name": "expiry", "value": "3"})
        del less_than_3_months["checked"]
        [less_than_1_month] = simulated_page.find_all("input", attrs={"name": "expiry", "value": "1"})
        less_than_1_month["checked"] = ""

        response = client.get(url, {"expiry": "1"}, headers={"HX-Request": "true"})
        update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
        response = client.get(url, {"expiry": "1"})
        fresh_page = parse_response_to_soup(response)
        assertSoupEqual(simulated_page, fresh_page)
