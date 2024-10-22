import datetime

import factory
import pytest
from dateutil.relativedelta import relativedelta
from django.template.defaultfilters import title, urlencode
from django.test import override_settings
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.common_apps.address.departments import department_from_postcode
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.users.enums import LackOfNIRReason
from itou.utils.templatetags import format_filters
from tests.companies.factories import CompanyFactory, CompanyWithMembershipAndJobsFactory
from tests.employee_record import factories as employee_record_factories
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import (
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
)
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assert_previous_step, assertSnapshotQueries, parse_response_to_soup


class TestListEmployeeRecords:
    URL = reverse_lazy("employee_record_views:list")

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        # User must be super user for UI first part (tmp)
        self.company = CompanyWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Elliot")
        self.user = self.company.members.get(first_name="Elliot")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(
            to_company=self.company,
            for_snapshot=True,
            job_seeker__city="",
            job_seeker__post_code="",
        )
        self.job_seeker = self.job_application.job_seeker
        self.employee_record = EmployeeRecord.from_job_application(self.job_application)
        self.employee_record.save()

    def test_permissions(self, client):
        """
        Non-eligible SIAE should not be able to access this list
        """
        company = CompanyWithMembershipAndJobsFactory(
            kind=factory.fuzzy.FuzzyChoice(set(CompanyKind) - set(Company.ASP_EMPLOYEE_RECORD_KINDS)),
        )
        client.force_login(company.members.get())

        response = client.get(self.URL)
        assert response.status_code == 403

    def test_new_employee_records_list(self, client):
        """
        Check if previous_step and back_url parmaeters are where we need them
        """
        record = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_company=self.company,
            job_application__job_seeker__last_name="Aaaaa",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=15),
        )
        record.update_as_ready()
        client.force_login(self.user)
        url = f"{self.URL}?status=READY"
        response = client.get(url)
        assert_previous_step(response, reverse("dashboard:index"))

        # Check record summary link has back_url set
        record_base_url = reverse("employee_record_views:summary", kwargs={"employee_record_id": record.pk})
        record_url = f"{record_base_url}?back_url={urlencode(url)}"
        assertContains(response, record_url)

    def test_redirection_with_missing_or_empty_status(self, client):
        client.force_login(self.user)

        response = client.get(self.URL)
        assertRedirects(response, reverse("employee_record_views:list") + "?status=NEW")

        response = client.get(self.URL, data={"status": ""})
        assertRedirects(response, reverse("employee_record_views:list") + "?status=NEW")

    def test_new_employee_records(self, client):
        """
        Check if new employee records / job applications are displayed in the list
        """
        client.force_login(self.user)

        response = client.get(self.URL, data={"status": Status.NEW})

        assertContains(response, format_filters.format_approval_number(self.job_application.approval.number))

    def test_status_filter(self, client):
        """
        Check status filter
        """
        # No status defined
        client.force_login(self.user)
        approval_number_formatted = format_filters.format_approval_number(self.job_application.approval.number)

        # For NEW
        response = client.get(self.URL, data={"status": Status.NEW})
        assertContains(response, approval_number_formatted)

        # More complete tests to come with fixtures files
        for status in [Status.SENT, Status.REJECTED, Status.PROCESSED]:
            response = client.get(self.URL, data={"status": status.value})
            assertNotContains(response, approval_number_formatted)

    def test_job_seeker_filter(self, client):
        approval_number_formatted = format_filters.format_approval_number(self.job_application.approval.number)
        other_employee_record = EmployeeRecordFactory(job_application__to_company=self.company)
        other_approval_number_formatted = format_filters.format_approval_number(other_employee_record.approval_number)
        client.force_login(self.user)

        response = client.get(self.URL, data={"status": Status.NEW})
        assertContains(response, approval_number_formatted)
        assertContains(response, other_approval_number_formatted)

        response = client.get(self.URL, data={"status": Status.NEW, "job_seeker": self.job_seeker.pk})
        assertContains(response, approval_number_formatted)
        assertNotContains(response, other_approval_number_formatted)

        response = client.get(self.URL, data={"status": Status.NEW, "job_seeker": 0})
        assertContains(response, "Sélectionnez un choix valide. 0 n’en fait pas partie.")
        assertContains(response, approval_number_formatted)
        assertContains(response, other_approval_number_formatted)

    def test_employee_records_approval_display(self, client):
        client.force_login(self.user)
        approval = self.job_application.approval
        approval.start_at = datetime.date(2023, 9, 2)
        approval.end_at = datetime.date(2024, 10, 11)
        approval.save()

        response = client.get(self.URL, data={"status": Status.NEW})

        assertContains(response, "<small>Date de début</small><strong>02/09/2023</strong>", html=True)
        assertContains(response, "<small>Date prévisionnelle de fin</small><strong>11/10/2024</strong>", html=True)

    def test_employee_record_to_disable(self, client, snapshot):
        client.force_login(self.user)

        response = client.get(self.URL, data={"status": Status.NEW})

        assert (
            str(
                parse_response_to_soup(
                    response,
                    selector=".employee-records-list .c-box--results__footer",
                    replace_in_attr=[self.job_application, self.employee_record],
                )
            )
            == snapshot()
        )

    @override_settings(TALLY_URL="https://tally.so")
    def test_employee_records_with_nir_associated_to_other(self, client, snapshot):
        client.force_login(self.user)
        self.job_seeker.jobseeker_profile.nir = ""
        self.job_seeker.jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
        self.job_seeker.jobseeker_profile.save(update_fields=("nir", "lack_of_nir_reason"))

        response = client.get(self.URL, data={"status": Status.NEW})

        assertContains(response, format_filters.format_approval_number(self.job_application.approval.number))
        # Item message alert
        assert str(
            parse_response_to_soup(
                response,
                selector=".employee-records-list .c-box--results__footer",
                replace_in_attr=[
                    (
                        "href",
                        f"https://tally.so/r/wzxQlg?employeerecord={self.employee_record.pk}&jobapplication={self.job_application.pk}",
                        (
                            "https://tally.so/r/wzxQlg"
                            "?employeerecord=[PK of EmployeeRecord]&jobapplication=[PK of JobApplication]"
                        ),
                    )
                ],
            )
        ) == snapshot(name="action")

    def test_rejected_without_custom_message(self, client, faker):
        client.force_login(self.user)

        record = employee_record_factories.EmployeeRecordWithProfileFactory(job_application__to_company=self.company)
        record.update_as_ready()
        record.update_as_sent(faker.asp_batch_filename(), 1, None)
        record.update_as_rejected("0012", "JSON Invalide", None)

        response = client.get(self.URL, data={"status": Status.REJECTED})
        assertContains(response, "Erreur 0012")
        assertContains(response, "JSON Invalide")

        hexa_commune = record.job_application.job_seeker.jobseeker_profile.hexa_commune
        assertContains(response, f"{department_from_postcode(hexa_commune.code)} - {title(hexa_commune.name)}")

    def test_rejected_custom_messages(self, client, subtests):
        client.force_login(self.user)

        record = employee_record_factories.EmployeeRecordWithProfileFactory(job_application__to_company=self.company)

        tests_specs = [
            (
                "3308",
                "Le champ Commune de Naissance doit être en cohérence avec le champ Département de Naissance",
                "Il semblerait que la commune de naissance sélectionnée ne corresponde pas au département",
            ),
            (
                "3417",
                "Le code INSEE de la commune de l’adresse doit correspondre à un code INSEE de commune référencée",
                "La commune de résidence du salarié n’est pas référencée",
            ),
            (
                "3435",
                "L’annexe de la structure doit être à l’état Valide ou Provisoire",
                "Nous n’avons pas encore reçu d’annexe financière à jour pour votre structure.",
            ),
            (
                "3436",
                "Un PASS IAE doit être unique pour un même SIRET",
                "La fiche salarié associée à ce PASS IAE et à votre SIRET a déjà été intégrée à l’ASP.",
            ),
        ]
        for err_code, err_message, custom_err_message in tests_specs:
            with subtests.test(err_code):
                record.status = Status.SENT
                record.update_as_rejected(err_code, err_message, "{}")

                response = client.get(self.URL, data={"status": Status.REJECTED})
                assertContains(response, f"Erreur {err_code}")
                assertNotContains(response, err_message)
                assertContains(response, custom_err_message)

    def _check_employee_record_order(self, client, url, first_job_application, second_job_application):
        response = client.get(url)
        response_text = response.content.decode(response.charset)
        # The index method raises ValueError if the value isn't found
        first_job_seeker_position = response_text.index(
            format_filters.format_approval_number(first_job_application.approval.number)
        )
        second_job_seeker_position = response_text.index(
            format_filters.format_approval_number(second_job_application.approval.number)
        )
        assert first_job_seeker_position < second_job_seeker_position

    def test_new_employee_records_sorted(self, client, snapshot):
        """
        Check if new employee records / job applications are correctly sorted
        """
        client.force_login(self.user)

        recordA = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_company=self.company,
            job_application__job_seeker__last_name="Aaaaa",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=15),
        )
        recordZ = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_company=self.company,
            job_application__job_seeker__last_name="Zzzzz",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=10),
        )

        # Zzzzz's hiring start is more recent
        self._check_employee_record_order(
            client, self.URL + "?status=NEW", recordZ.job_application, recordA.job_application
        )

        # order with -hiring_start_at is the default
        self._check_employee_record_order(
            client, self.URL + "?status=NEW&order=-hiring_start_at", recordZ.job_application, recordA.job_application
        )
        self._check_employee_record_order(
            client, self.URL + "?status=NEW&order=hiring_start_at", recordA.job_application, recordZ.job_application
        )

        # Zzzzz after Aaaaa
        self._check_employee_record_order(
            client, self.URL + "?status=NEW&order=name", recordA.job_application, recordZ.job_application
        )
        self._check_employee_record_order(
            client, self.URL + "?status=NEW&order=-name", recordZ.job_application, recordA.job_application
        )

        with assertSnapshotQueries(snapshot(name="employee records")):
            client.get(self.URL, data={"status": Status.NEW})

    def test_rejected_employee_records_sorted(self, client, snapshot):
        client.force_login(self.user)

        recordA = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_company=self.company,
            job_application__job_seeker__last_name="Aaaaa",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=15),
        )
        recordZ = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_company=self.company,
            job_application__job_seeker__last_name="Zzzzz",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=10),
        )
        for i, record in enumerate((recordA, recordZ)):
            record.update_as_ready()
            record.update_as_sent(f"RIAE_FS_2021041013000{i}.json", 1, None)
            record.update_as_rejected("0012", "JSON Invalide", None)

        # Zzzzz's hiring start is more recent
        self._check_employee_record_order(
            client, self.URL + "?status=REJECTED", recordZ.job_application, recordA.job_application
        )

        # order with -hiring_start_at is the default
        self._check_employee_record_order(
            client,
            self.URL + "?status=REJECTED&order=-hiring_start_at",
            recordZ.job_application,
            recordA.job_application,
        )
        self._check_employee_record_order(
            client,
            self.URL + "?status=REJECTED&order=hiring_start_at",
            recordA.job_application,
            recordZ.job_application,
        )

        # Zzzzz after Aaaaa
        self._check_employee_record_order(
            client,
            self.URL + "?status=REJECTED&order=name",
            recordA.job_application,
            recordZ.job_application,
        )
        self._check_employee_record_order(
            client,
            self.URL + "?status=REJECTED&order=-name",
            recordZ.job_application,
            recordA.job_application,
        )

    def test_ready_employee_records_sorted(self, client, snapshot):
        client.force_login(self.user)

        recordA = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_company=self.company,
            job_application__job_seeker__last_name="Aaaaa",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=15),
        )
        recordZ = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_company=self.company,
            job_application__job_seeker__last_name="Zzzzz",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=10),
        )
        for record in (recordA, recordZ):
            record.update_as_ready()

        # Zzzzz's hiring start is more recent
        self._check_employee_record_order(
            client, self.URL + "?status=READY", recordZ.job_application, recordA.job_application
        )

        # order with -hiring_start_at is the default
        self._check_employee_record_order(
            client,
            self.URL + "?status=READY&order=-hiring_start_at",
            recordZ.job_application,
            recordA.job_application,
        )
        self._check_employee_record_order(
            client,
            self.URL + "?status=READY&order=hiring_start_at",
            recordA.job_application,
            recordZ.job_application,
        )

        # Zzzzz after Aaaaa
        self._check_employee_record_order(
            client,
            self.URL + "?status=READY&order=name",
            recordA.job_application,
            recordZ.job_application,
        )
        self._check_employee_record_order(
            client,
            self.URL + "?status=READY&order=-name",
            recordZ.job_application,
            recordA.job_application,
        )

    def test_display_result_count(self, client):
        client.force_login(self.user)
        response = client.get(self.URL, data={"status": Status.NEW})
        assertContains(response, "1 résultat")

        EmployeeRecordFactory(job_application__to_company=self.company)
        response = client.get(self.URL, data={"status": Status.NEW})
        assertContains(response, "2 résultats")

        response = client.get(self.URL, data={"status": Status.READY})
        assertContains(response, "0 résultat")

    def test_htmx(self, client):
        client.force_login(self.user)
        response = client.get(self.URL, {"status": "NEW"})
        simulated_page = parse_response_to_soup(response)

        [new_status] = simulated_page.find_all("input", attrs={"name": "status", "value": "NEW"})
        del new_status["checked"]
        [ready_status] = simulated_page.find_all("input", attrs={"name": "status", "value": "READY"})
        ready_status["checked"] = ""

        response = client.get(self.URL, {"status": "READY"}, headers={"HX-Request": "true"})
        update_page_with_htmx(simulated_page, f"form[hx-get='{self.URL}']", response)

        response = client.get(self.URL, data={"status": Status.READY})
        fresh_page = parse_response_to_soup(response)
        assertSoupEqual(simulated_page, fresh_page)

    def test_htmx_order(self, client):
        client.force_login(self.user)
        response = client.get(self.URL, {"status": "NEW"})
        simulated_page = parse_response_to_soup(response)

        # Page JavaScript does that.
        [order_field] = simulated_page.find_all("input", attrs={"name": "order"})
        order_field["value"] = "name"
        response = client.get(self.URL, {"status": "NEW", "order": "name"}, headers={"HX-Request": "true"})
        update_page_with_htmx(simulated_page, f"form[hx-get='{self.URL}']", response)

        response = client.get(self.URL, {"status": "NEW", "order": "name"})
        fresh_page = parse_response_to_soup(response)
        assertSoupEqual(simulated_page, fresh_page)

    def test_htmx_new_employee_record_updates_badge_count(self, client):
        client.force_login(self.user)
        response = client.get(self.URL, {"status": "NEW"})
        simulated_page = parse_response_to_soup(response)
        # This new application should update the counter badge on NEW.
        new_job_app = JobApplicationWithApprovalNotCancellableFactory(to_company=self.company)

        [new_status] = simulated_page.find_all("input", attrs={"name": "status", "value": "NEW"})
        del new_status["checked"]
        [ready_status] = simulated_page.find_all("input", attrs={"name": "status", "value": "READY"})
        ready_status["checked"] = ""

        response = client.get(self.URL, {"status": "READY"}, headers={"HX-Request": "true"})
        update_page_with_htmx(simulated_page, f"form[hx-get='{self.URL}']", response)

        response = client.get(self.URL, data={"status": Status.READY})
        fresh_page = parse_response_to_soup(response)
        # Reloading the job seekers select2 with HTMX would change the
        # select input the form listens to via hx-trigger, causing the
        # form to no longer pick up change events from the select2.
        # Given that options aren’t added frequently to that dropdown, wait
        # until the next full page load to get new job seekers.
        [new_jobseeker_opt] = fresh_page.select(f'#id_job_seeker > option[value="{new_job_app.job_seeker_id}"]')
        new_jobseeker_opt.decompose()
        assertSoupEqual(simulated_page, fresh_page)


def test_an_active_siae_without_convention_can_not_access_the_view(client):
    siae = CompanyFactory(
        use_employee_record=True,
        source=Company.SOURCE_STAFF_CREATED,
        convention=None,
        with_membership=True,
    )
    client.force_login(siae.members.first())

    response = client.get(reverse("employee_record_views:list"))
    assert response.status_code == 403
