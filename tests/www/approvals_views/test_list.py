import datetime
import random
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.template.defaultfilters import urlencode
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.companies.models import Company
from itou.www.approvals_views.views import ApprovalListView
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory, ContractFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import PAGINATION_PAGE_ONE_MARKUP, assertSnapshotQueries, parse_response_to_soup


class TestApprovalsListView:
    TABS_CLASS = "s-tabs-01__nav nav nav-tabs"

    def test_anonymous_user(self, client):
        url = reverse("approvals:list")
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_list_view(self, client):
        approval = ApprovalFactory(with_jobapplication=True, with_ongoing_contract=True)
        job_application = approval.jobapplication_set.get()

        approval_for_other_company = ApprovalFactory(with_jobapplication=True)

        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "1 résultat")
        assertContains(response, approval.user.get_full_name())
        assertNotContains(response, approval_for_other_company.user.get_full_name())

        employee_base_url = reverse("employees:detail", kwargs={"public_id": approval.user.public_id})
        assertContains(response, f"{employee_base_url}?approval={approval.pk}&back_url={urlencode(url)}")
        assertContains(response, self.TABS_CLASS)

    def test_multiple_approvals_for_the_same_user(self, client):
        approval = ApprovalFactory(with_jobapplication=True, with_ongoing_contract=True)
        job_application = approval.jobapplication_set.get()

        another_approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=job_application.to_company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=job_application.to_company,
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
        approval = ApprovalFactory(with_jobapplication=True, with_ongoing_contract=True)

        # Create another job_application on the same approval / siae
        job_application = approval.jobapplication_set.get()
        job_application.pk = None
        job_application.resume = None  # It's a OneToOneField
        job_application.save()

        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:list")
        response = client.get(url)

        assertContains(response, "1 résultat")

    def test_job_seeker_filters(self, client, snapshot):
        approval = ApprovalFactory(
            with_jobapplication=True,
            with_ongoing_contract=True,
            user__first_name="Jean",
            user__last_name="Vier",
        )
        job_application = approval.jobapplication_set.get()
        approval_same_company = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=job_application.to_company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=job_application.to_company,
            user__first_name="Seb",
            user__last_name="Tambre",
        )
        approval_other_company = ApprovalFactory(with_jobapplication=True, with_ongoing_contract=True)

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("approvals:list")
        with assertSnapshotQueries(snapshot(name="approvals list")):
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
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        future_approval = ApprovalFactory(
            start_at=now + datetime.timedelta(days=1),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        valid_approval = ApprovalFactory(
            start_at=now - datetime.timedelta(days=365),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        suspended_approval = ApprovalFactory(
            start_at=now - datetime.timedelta(days=365),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
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
            """<span class="badge badge-sm text-wrap rounded-pill bg-success-lighter text-success">
                <i class="ri-pass-valid-line ri-xl" aria-hidden="true"></i>
                PASS IAE valide
            </span>""",
            html=True,
        )

        assertContains(
            response,
            """<span class="badge badge-sm text-wrap rounded-pill bg-success-lighter text-success">
                <i class="ri-pass-valid-line ri-xl" aria-hidden="true"></i>
                PASS IAE valide (non démarré)
            </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-sm text-wrap rounded-pill bg-success-lighter text-success">
                <i class="ri-pass-pending-line ri-xl" aria-hidden="true"></i>
                PASS IAE valide (suspendu)
            </span>""",
            html=True,
        )
        assertContains(
            response,
            """<span class="badge badge-sm text-wrap rounded-pill bg-danger-lighter text-danger">
                <i class="ri-pass-expired-line ri-xl" aria-hidden="true"></i>
                PASS IAE expiré
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
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        in_less_than_3_months = now + relativedelta(days=80)
        approval_3 = ApprovalFactory(
            start_at=in_less_than_3_months - relativedelta(years=2),
            end_at=in_less_than_3_months,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        in_less_than_7_mmonths = now + relativedelta(days=200)
        approval_7 = ApprovalFactory(
            start_at=in_less_than_7_mmonths - relativedelta(years=2),
            end_at=in_less_than_7_mmonths,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        ApprovalFactory(
            start_at=now - relativedelta(years=1),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
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

    @patch("itou.www.approvals_views.views.ApprovalListView.paginate_by", 1)
    def test_filter_default(self, client):
        company = CompanyFactory(with_membership=True)
        # Make sure we have access to page 2
        ApprovalFactory.create_batch(
            ApprovalListView.paginate_by + 1,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        employer = company.members.first()
        client.force_login(employer)

        list_url = reverse("approvals:list")
        response = client.get(list_url)
        # Check that the default "Fin du parcours en IAE" value "Tous" is selected
        expiry_all_input = parse_response_to_soup(response, "input[name='expiry'][value='']")
        assert expiry_all_input.has_attr("checked")
        assertContains(response, PAGINATION_PAGE_ONE_MARKUP % (list_url + "?page=1"), html=True)
        # Check that the default "Statut du contrat" value "Contrats en cours[…]" is selected
        contract_status_input = parse_response_to_soup(response, "input[name='contract_status'][value='']")
        assert contract_status_input.has_attr("checked")
        assertContains(response, PAGINATION_PAGE_ONE_MARKUP % (list_url + "?page=1"), html=True)

        response = client.get(f"{list_url}?page=2")
        # Check that the default "Fin du parcours en IAE" value "Tous" is selected
        expiry_all_input = parse_response_to_soup(response, "input[name='expiry'][value='']")
        assert expiry_all_input.has_attr("checked")
        # Check that the default "Statut du contrat" value "Contrats en cours[…]" is selected
        contract_status_input = parse_response_to_soup(response, "input[name='contract_status'][value='']")
        assert contract_status_input.has_attr("checked")

    def test_approval_contract_filters(self, client):
        now = timezone.localdate()
        company = CompanyFactory(with_membership=True)

        a_year_ago = now - relativedelta(days=365)
        less_than_3_months_ago = now - relativedelta(days=85)
        more_than_3_months_ago = now - relativedelta(days=95)
        in_future = now + relativedelta(days=10)

        approval_kwargs = {
            "start_at": a_year_ago,
            "end_at": now + relativedelta(days=10),
        }
        # Contracts overlapping approval
        approval_with_ongoing_contract = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=a_year_ago,
            with_ongoing_contract__end_date=None,
            **approval_kwargs,
        )
        approval_with_just_ended_contract = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=a_year_ago,
            with_ongoing_contract__end_date=less_than_3_months_ago,
            **approval_kwargs,
        )
        approval_with_ended_contract = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=a_year_ago,
            with_ongoing_contract__end_date=more_than_3_months_ago,
            **approval_kwargs,
        )
        approval_with_ended_in_future_contract = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=a_year_ago,
            with_ongoing_contract__end_date=in_future,
            **approval_kwargs,
        )
        approval_with_multiple_contracts = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=a_year_ago,
            with_ongoing_contract__end_date=more_than_3_months_ago,
            **approval_kwargs,
        )
        ContractFactory(
            job_seeker=approval_with_multiple_contracts.user,
            company=approval_with_multiple_contracts.jobapplication_set.first().to_company,
            start_date=more_than_3_months_ago,
            end_date=less_than_3_months_ago,
        )
        # Contracts not overlapping approval
        approval_with_contract_started_ended_before_approval = ApprovalFactory(
            start_at=now,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=now - relativedelta(days=20),
            with_ongoing_contract__end_date=now - relativedelta(days=15),
        )
        approval_with_contract_started_ended_after_approval = ApprovalFactory(
            start_at=a_year_ago,
            end_at=now - relativedelta(days=10),
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=now - relativedelta(days=5),
            with_ongoing_contract__end_date=now,
        )
        # Also check job application hire dates (hire_start_at, since the end date is often left empty)
        # if no contract was found.
        approval_with_just_started_hire = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=less_than_3_months_ago,
            with_jobapplication__hiring_end_at=None,
        )
        approval_with_started_hire_long_ago = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=more_than_3_months_ago,
            with_jobapplication__hiring_end_at=None,
        )
        approval_with_started_in_future_hire = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=in_future,
            with_jobapplication__hiring_end_at=in_future,
        )

        employer = company.members.first()
        client.force_login(employer)

        # All approvals
        url = f"{reverse('approvals:list')}?contract_status=all"
        response = client.get(url)
        assertContains(response, "10 résultats")
        expected_approvals = [
            approval_with_ongoing_contract,
            approval_with_just_ended_contract,
            approval_with_ended_contract,
            approval_with_ended_in_future_contract,
            approval_with_multiple_contracts,
            approval_with_contract_started_ended_before_approval,
            approval_with_contract_started_ended_after_approval,
            approval_with_just_started_hire,
            approval_with_started_hire_long_ago,
            approval_with_started_in_future_hire,
        ]
        for approval in expected_approvals:
            assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))

        # Approvals associated to ongoing contracts (ended <3 months ago)
        url = f"{reverse('approvals:list')}" + random.choice(["", "?contract_status="])
        response = client.get(url)
        print(str(parse_response_to_soup(response)))
        assertContains(response, "6 résultats")
        expected_approvals = [
            approval_with_ongoing_contract,
            approval_with_just_ended_contract,
            approval_with_ended_in_future_contract,
            approval_with_multiple_contracts,
            approval_with_just_started_hire,
            approval_with_started_in_future_hire,
        ]
        for approval in expected_approvals:
            assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
        unexpected_approvals = [
            approval_with_ended_contract,
            approval_with_contract_started_ended_before_approval,
            approval_with_contract_started_ended_after_approval,
            approval_with_started_hire_long_ago,
        ]
        for approval in unexpected_approvals:
            assertNotContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))

        # Approvals associated to ended contracts (ended >3 months ago)
        url = f"{reverse('approvals:list')}?contract_status=ended"
        response = client.get(url)
        assertContains(response, "4 résultats")
        expected_approvals = [
            approval_with_ended_contract,
            approval_with_contract_started_ended_before_approval,
            approval_with_contract_started_ended_after_approval,
            approval_with_started_hire_long_ago,
        ]
        for approval in expected_approvals:
            assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
        unexpected_approvals = [
            approval_with_ongoing_contract,
            approval_with_just_ended_contract,
            approval_with_ended_in_future_contract,
            approval_with_multiple_contracts,
            approval_with_just_started_hire,
            approval_with_started_in_future_hire,
        ]
        for approval in unexpected_approvals:
            assertNotContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))

    def test_update_with_htmx(self, client):
        now = timezone.localdate()
        company = CompanyFactory(with_membership=True)

        in_less_than_1_month = now + relativedelta(days=20)
        approval_1 = ApprovalFactory(
            start_at=in_less_than_1_month - relativedelta(years=2),
            end_at=in_less_than_1_month,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        in_less_than_3_months = now + relativedelta(days=80)
        approval_3 = ApprovalFactory(
            start_at=in_less_than_3_months - relativedelta(years=2),
            end_at=in_less_than_3_months,
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
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

    def test_no_tabs_when_siae_does_not_have_access_to_employee_records(self, client):
        company = CompanyFactory(
            convention=None,
            use_employee_record=True,
            with_membership=True,
            source=Company.SOURCE_STAFF_CREATED,
        )
        ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
        )
        client.force_login(company.members.get())
        response = client.get(reverse("approvals:list"))
        assertContains(response, "1 résultat")
        assertNotContains(response, self.TABS_CLASS)
