import datetime
import random
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.template.defaultfilters import urlencode
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.companies.models import Company
from itou.job_applications.enums import JobApplicationState
from itou.www.approvals_views.views import ApprovalDisplayKind, ApprovalListView
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory, ContractFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import (
    PAGINATION_PAGE_ONE_MARKUP,
    parse_response_to_soup,
    pretty_indented,
)


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

        assert response.context["display_kind"] == ApprovalDisplayKind.TABLE  # Check default display kind

        assertContains(response, "1 résultat")
        assertContains(response, approval.user.get_inverted_full_name())
        assertNotContains(response, approval_for_other_company.user.get_inverted_full_name())

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
        assertContains(
            response, f'aria-label="Voir les informations de {approval.user.get_inverted_full_name()}"', count=1
        )
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
            (approval_same_company.user_id, "TAMBRE Seb"),
            (approval.user_id, "VIER Jean"),
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
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)

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
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)

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
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
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
        assertContains(response, PAGINATION_PAGE_ONE_MARKUP % (list_url + "?page=1"), html=True)
        # Check that the default "Fin du parcours en IAE" value "Tous" is selected
        expiry_all_input = parse_response_to_soup(response, "input[name='expiry'][value='']")
        assert expiry_all_input.has_attr("checked")
        # Check that the default "Statut du contrat" value "Tous" is selected
        contract_status_input = parse_response_to_soup(response, "input[name='contract_status'][value='']")
        assert contract_status_input.has_attr("checked")

        response = client.get(f"{list_url}?page=2")
        # Check that the default "Fin du parcours en IAE" value "Tous" is selected
        expiry_all_input = parse_response_to_soup(response, "input[name='expiry'][value='']")
        assert expiry_all_input.has_attr("checked")
        # Check that the default "Statut du contrat" value "Contrats en cours[…]" is selected
        contract_status_input = parse_response_to_soup(response, "input[name='contract_status'][value='']")
        assert contract_status_input.has_attr("checked")

    def test_approval_contract_filters(self, client, snapshot):
        now = timezone.localdate()
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)

        a_year_ago = now - datetime.timedelta(days=365)
        less_than_3_months_ago = now - datetime.timedelta(days=85)
        more_than_3_months_ago = now - datetime.timedelta(days=95)
        in_future = now + datetime.timedelta(days=10)

        approval_kwargs = {
            "start_at": a_year_ago,
            "end_at": now + datetime.timedelta(days=10),
        }

        # End dates not older than 90 days ago
        # ------------------------------------
        approval_with_ongoing_contract = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=more_than_3_months_ago,  # contract has precedence
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
            with_jobapplication__hiring_end_at=more_than_3_months_ago,  # contract has precedence
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=a_year_ago,
            with_ongoing_contract__end_date=less_than_3_months_ago,
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
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
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
        approval_with_hiring_end_at_future = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=a_year_ago,
            with_jobapplication__hiring_end_at=in_future,
            **approval_kwargs,
        )
        approval_with_hiring_end_at_recent = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=a_year_ago,
            with_jobapplication__hiring_end_at=less_than_3_months_ago,
            start_at=a_year_ago,
            end_at=more_than_3_months_ago,  # hiring_end_at has precedence
        )
        approval_with_multiple_job_apps_same_company = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=a_year_ago,
            with_jobapplication__hiring_end_at=more_than_3_months_ago,
            **approval_kwargs,
        )
        JobApplicationFactory(
            job_seeker=approval_with_multiple_job_apps_same_company.user,
            approval=approval_with_multiple_job_apps_same_company,
            to_company=company,
            hiring_end_at=less_than_3_months_ago,
            state=JobApplicationState.ACCEPTED,
        )
        approval_end_date_future = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            start_at=a_year_ago,
            end_at=in_future,
        )
        approval_end_date_recent = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            start_at=a_year_ago,
            end_at=less_than_3_months_ago,
        )

        # End dates older than 90 days ago
        # --------------------------------
        approval_with_ended_contract = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=less_than_3_months_ago,  # contract has precedence
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=a_year_ago,
            with_ongoing_contract__end_date=more_than_3_months_ago,
            start_at=a_year_ago,
            end_at=less_than_3_months_ago,  # contract has precedence
        )
        approval_with_contract_started_ended_before_approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=a_year_ago,
            with_jobapplication__hiring_end_at=more_than_3_months_ago,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=now - datetime.timedelta(days=20),
            with_ongoing_contract__end_date=now - datetime.timedelta(days=15),
            start_at=now,
            end_at=in_future,  # hiring_end_at has precedence
        )
        approval_with_contract_started_ended_after_approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=a_year_ago,
            with_jobapplication__hiring_end_at=more_than_3_months_ago,
            with_ongoing_contract=True,
            with_ongoing_contract__company=company,
            with_ongoing_contract__start_date=now - datetime.timedelta(days=5),
            with_ongoing_contract__end_date=now,
            start_at=a_year_ago,
            end_at=now - datetime.timedelta(days=10),  # hiring_end_at has precedence
        )
        approval_with_hiring_end_at_old = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=a_year_ago,
            with_jobapplication__hiring_end_at=more_than_3_months_ago,
            start_at=a_year_ago,
            end_at=less_than_3_months_ago,  # hiring_end_at has precedence
        )
        approval_with_multiple_job_apps = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=a_year_ago,
            with_jobapplication__hiring_end_at=more_than_3_months_ago,
            **approval_kwargs,
        )
        JobApplicationFactory(
            job_seeker=approval_with_multiple_job_apps.user,
            approval=approval_with_multiple_job_apps,
            hiring_end_at=less_than_3_months_ago,  # in another company, will not be looked up
            state=JobApplicationState.ACCEPTED,
        )
        approval_end_date_old = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
            with_jobapplication__hiring_start_at=None,
            with_jobapplication__hiring_end_at=None,
            start_at=a_year_ago,
            end_at=more_than_3_months_ago,
        )

        approvals_with_ongoing_contracts = [
            approval_with_ongoing_contract,
            approval_with_just_ended_contract,
            approval_with_ended_in_future_contract,
            approval_with_multiple_contracts,
            approval_with_hiring_end_at_future,
            approval_with_hiring_end_at_recent,
            approval_with_multiple_job_apps_same_company,
            approval_end_date_future,
            approval_end_date_recent,
        ]
        approvals_with_ended_contracts = [
            approval_with_ended_contract,
            approval_with_contract_started_ended_before_approval,
            approval_with_contract_started_ended_after_approval,
            approval_with_hiring_end_at_old,
            approval_with_multiple_job_apps,
            approval_end_date_old,
        ]

        employer = company.members.first()
        client.force_login(employer)

        # All approvals
        url = f"{reverse('approvals:list')}" + random.choice(["", "?contract_status=all", "?contract_status=rand0m"])
        response = client.get(url)
        assertContains(response, "15 résultats")
        for approval in approvals_with_ongoing_contracts + approvals_with_ended_contracts:
            assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))

        # Approvals associated to ongoing contracts (ended less than 90 days ago)
        url = f"{reverse('approvals:list')}?contract_status=ongoing"
        with assertSnapshotQueries(snapshot(name="approvals list ongoing contracts filter")):
            response = client.get(url)
        assertContains(response, "9 résultats")
        for approval in approvals_with_ongoing_contracts:
            assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
        for approval in approvals_with_ended_contracts:
            assertNotContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))

        # Approvals associated to ended contracts (ended more than 90 days ago)
        url = f"{reverse('approvals:list')}?contract_status=ended"
        with assertSnapshotQueries(snapshot(name="approvals list ended contracts filter")):
            response = client.get(url)
        assertContains(response, "6 résultats")
        for approval in approvals_with_ended_contracts:
            assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
        for approval in approvals_with_ongoing_contracts:
            assertNotContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))

    def test_update_with_htmx(self, client):
        now = timezone.localdate()
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)

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

    def test_update_display_kind_with_htmx(self, client):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)

        approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company=company,
        )
        employer = company.members.first()
        client.force_login(employer)

        url = reverse("approvals:list")
        response = client.get(url, {"display": ApprovalDisplayKind.TABLE})
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}), count=2)
        simulated_page = parse_response_to_soup(response)

        # Switch from table to list
        [display_input] = simulated_page.find_all(id="display-kind")
        display_input["value"] = ApprovalDisplayKind.LIST.value
        response = client.get(url, {"display": ApprovalDisplayKind.LIST}, headers={"HX-Request": "true"})
        update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
        response = client.get(url, {"display": ApprovalDisplayKind.LIST})
        assertContains(response, "1 résultat")
        assertContains(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}), count=1)
        fresh_page = parse_response_to_soup(response)
        assertSoupEqual(simulated_page, fresh_page)

        # Switch from list to table
        [display_input] = simulated_page.find_all(id="display-kind")
        display_input["value"] = ApprovalDisplayKind.TABLE.value
        response = client.get(url, {"display": ApprovalDisplayKind.TABLE}, headers={"HX-Request": "true"})
        update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
        response = client.get(url, {"display": ApprovalDisplayKind.TABLE})
        fresh_page = parse_response_to_soup(response)
        assertSoupEqual(simulated_page, fresh_page)

    def test_no_tabs_when_siae_does_not_have_access_to_employee_records(self, client):
        company = CompanyFactory(
            convention=None,
            use_employee_record=True,
            with_membership=True,
            source=Company.SOURCE_STAFF_CREATED,
            subject_to_iae_rules=True,
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


def test_list_and_table_empty_snapshot(client, snapshot):
    company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
    client.force_login(company.members.get())
    url = reverse("approvals:list")

    for display_param in [
        {},
        {"display": ApprovalDisplayKind.LIST},
        {"display": ApprovalDisplayKind.TABLE},
    ]:
        response = client.get(url, display_param)
        page = parse_response_to_soup(response, selector="#approvals-list")
        assert pretty_indented(page) == snapshot(name="empty")


@freeze_time("2025-01-01")
def test_table_and_list_snapshot(client, snapshot):
    approval = ApprovalFactory(with_jobapplication=True, for_snapshot=True)
    job_application = approval.jobapplication_set.get()
    client.force_login(job_application.to_company.members.first())
    url = reverse("approvals:list")

    response = client.get(url, {"display": ApprovalDisplayKind.TABLE})
    page = parse_response_to_soup(
        response,
        selector="#approvals-list",
        replace_in_attr=[
            (
                "href",
                f"approval={approval.pk}",
                "approval=[PK of Approval]",
            ),
        ],
    )
    assert pretty_indented(page) == snapshot(name="table")

    response = client.get(url, {"display": ApprovalDisplayKind.LIST})
    page = parse_response_to_soup(
        response,
        selector="#approvals-list",
        replace_in_attr=[
            (
                "href",
                f"approval={approval.pk}",
                "approval=[PK of Approval]",
            ),
        ],
    )
    assert pretty_indented(page) == snapshot(name="list")
