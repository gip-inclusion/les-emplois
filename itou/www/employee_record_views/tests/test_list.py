from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone

from itou.employee_record import factories as employee_record_factories
from itou.employee_record.enums import Status
from itou.job_applications.factories import JobApplicationWithApprovalNotCancellableFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.utils.test import TestCase


class ListEmployeeRecordsTest(TestCase):
    def setUp(self):
        # User must be super user for UI first part (tmp)
        self.siae = SiaeWithMembershipAndJobsFactory(
            name="Evil Corp.", membership__user__first_name="Elliot", membership__user__is_superuser=True
        )
        self.siae_without_perms = SiaeWithMembershipAndJobsFactory(
            kind="EITI", name="A-Team", membership__user__first_name="Hannibal"
        )
        self.user = self.siae.members.get(first_name="Elliot")
        self.user_without_perms = self.siae_without_perms.members.get(first_name="Hannibal")
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(to_siae=self.siae)
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:list")

    def test_permissions(self):
        """
        Non-eligible SIAE should not be able to access this list
        """
        self.client.force_login(self.user_without_perms)

        response = self.client.get(self.url)

        assert response.status_code == 403

    def test_new_employee_records(self):
        """
        Check if new employee records / job applications are displayed in the list
        """
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        assert response.status_code == 200
        self.assertContains(response, self.job_seeker.get_full_name().title())

    def test_status_filter(self):
        """
        Check status filter
        """
        # No status defined
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        job_seeker_name = self.job_seeker.get_full_name().title()

        self.assertContains(response, job_seeker_name)

        # Or NEW
        response = self.client.get(self.url + "?status=NEW")
        self.assertContains(response, job_seeker_name)

        # More complete tests to come with fixtures files
        for status in [Status.SENT, Status.REJECTED, Status.PROCESSED]:
            response = self.client.get(self.url + f"?status={status.value}")
            self.assertNotContains(response, job_seeker_name)

    def test_employee_records_with_hiring_end_at(self):
        self.client.force_login(self.user)
        hiring_end_at = self.job_application.hiring_end_at

        response = self.client.get(self.url)

        assert response.status_code == 200
        self.assertContains(response, f"Fin de contrat :&nbsp;<b>{hiring_end_at.strftime('%e').lstrip()}")

    def test_employee_records_without_hiring_end_at(self):
        self.client.force_login(self.user)
        self.job_application.hiring_end_at = None
        self.job_application.save()

        response = self.client.get(self.url)

        assert response.status_code == 200
        self.assertContains(response, "Fin de contrat :&nbsp;<b>Non renseigné")

    def test_rejected_without_custom_message(self):
        self.client.force_login(self.user)

        record = employee_record_factories.EmployeeRecordWithProfileFactory(job_application__to_siae=self.siae)
        record.update_as_ready()
        record.update_as_sent("RIAE_FS_20210410130002.json", 1)
        record.update_as_rejected("0012", "JSON Invalide")

        response = self.client.get(self.url + "?status=REJECTED")
        assert response.status_code == 200
        self.assertContains(response, "Erreur 0012")
        self.assertContains(response, "JSON Invalide")

    def test_rejected_custom_messages(self):
        self.client.force_login(self.user)

        record = employee_record_factories.EmployeeRecordWithProfileFactory(job_application__to_siae=self.siae)

        tests_specs = [
            (
                "3308",
                "Le champ Commune de Naissance doit être en cohérence avec le champ Département de Naissance",
                "Il semblerait que la commune de naissance sélectionnée ne corresponde pas au département",
            ),
            (
                "3417",
                "Le code INSEE de la commune de l’adresse doit correspondre à un code INSEE de commune référencée",
                "L’adresse renseignée n’est pas référencée.",
            ),
            (
                "3435",
                "L’annexe de la structure doit être à l’état Valide ou Provisoire",
                "Nous n’avons pas encore reçu d’annexe financière à jour pour votre structure.",
            ),
            (
                "3436",
                "Un PASS IAE doit être unique pour un même SIRET",
                "La fiche salarié associée à ce PASS IAE et à votre SIRET a déjà été intégrée à l’ASP.",
            ),
        ]
        for err_code, err_message, custom_err_message in tests_specs:
            with self.subTest(err_code):
                record.status = Status.SENT
                record.update_as_rejected(err_code, err_message)

                response = self.client.get(self.url + "?status=REJECTED")
                assert response.status_code == 200
                self.assertContains(response, f"Erreur {err_code}")
                self.assertNotContains(response, err_message)
                self.assertContains(response, custom_err_message)

    def _check_employee_record_order(self, url, first_job_seeker, second_job_seeker):
        response = self.client.get(url)
        assert response.status_code == 200
        response_text = response.content.decode(response.charset)
        # The index method raises ValueError if the value isn't found
        first_job_seeker_position = response_text.index(first_job_seeker.get_full_name().title())
        second_job_seeker_position = response_text.index(second_job_seeker.get_full_name().title())
        assert first_job_seeker_position < second_job_seeker_position

    def test_new_employee_records_sorted(self):
        """
        Check if new employee records / job applications are correctly sorted
        """
        self.client.force_login(self.user)

        job_applicationA = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae, job_seeker__last_name="Aaaaa", hiring_start_at=timezone.now() - relativedelta(days=15)
        )
        job_applicationZ = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae, job_seeker__last_name="Zzzzz", hiring_start_at=timezone.now() - relativedelta(days=10)
        )

        # Zzzzz's hiring start is more recent
        self._check_employee_record_order(self.url, job_applicationZ.job_seeker, job_applicationA.job_seeker)

        # order with -hiring_start_at is the default
        self._check_employee_record_order(
            self.url + "?order=-hiring_start_at", job_applicationZ.job_seeker, job_applicationA.job_seeker
        )
        self._check_employee_record_order(
            self.url + "?order=hiring_start_at", job_applicationA.job_seeker, job_applicationZ.job_seeker
        )

        # Zzzzz after Aaaaa
        self._check_employee_record_order(
            self.url + "?order=name", job_applicationA.job_seeker, job_applicationZ.job_seeker
        )
        self._check_employee_record_order(
            self.url + "?order=-name", job_applicationZ.job_seeker, job_applicationA.job_seeker
        )

    def test_rejected_employee_records_sorted(self):
        self.client.force_login(self.user)

        recordA = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_siae=self.siae,
            job_application__job_seeker__last_name="Aaaaa",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=15),
        )
        recordZ = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_siae=self.siae,
            job_application__job_seeker__last_name="Zzzzz",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=10),
        )
        for i, record in enumerate((recordA, recordZ)):
            record.update_as_ready()
            record.update_as_sent(f"RIAE_FS_2021041013000{i}.json", 1)
            record.update_as_rejected("0012", "JSON Invalide")

        # Zzzzz's hiring start is more recent
        self._check_employee_record_order(
            self.url + "?status=REJECTED", recordZ.job_application.job_seeker, recordA.job_application.job_seeker
        )

        # order with -hiring_start_at is the default
        self._check_employee_record_order(
            self.url + "?status=REJECTED&order=-hiring_start_at",
            recordZ.job_application.job_seeker,
            recordA.job_application.job_seeker,
        )
        self._check_employee_record_order(
            self.url + "?status=REJECTED&order=hiring_start_at",
            recordA.job_application.job_seeker,
            recordZ.job_application.job_seeker,
        )

        # Zzzzz after Aaaaa
        self._check_employee_record_order(
            self.url + "?status=REJECTED&order=name",
            recordA.job_application.job_seeker,
            recordZ.job_application.job_seeker,
        )
        self._check_employee_record_order(
            self.url + "?status=REJECTED&order=-name",
            recordZ.job_application.job_seeker,
            recordA.job_application.job_seeker,
        )

    def test_ready_employee_records_sorted(self):
        self.client.force_login(self.user)

        recordA = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_siae=self.siae,
            job_application__job_seeker__last_name="Aaaaa",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=15),
        )
        recordZ = employee_record_factories.EmployeeRecordWithProfileFactory(
            job_application__to_siae=self.siae,
            job_application__job_seeker__last_name="Zzzzz",
            job_application__hiring_start_at=timezone.now() - relativedelta(days=10),
        )
        for record in (recordA, recordZ):
            record.update_as_ready()

        # Zzzzz's hiring start is more recent
        self._check_employee_record_order(
            self.url + "?status=READY", recordZ.job_application.job_seeker, recordA.job_application.job_seeker
        )

        # order with -hiring_start_at is the default
        self._check_employee_record_order(
            self.url + "?status=READY&order=-hiring_start_at",
            recordZ.job_application.job_seeker,
            recordA.job_application.job_seeker,
        )
        self._check_employee_record_order(
            self.url + "?status=READY&order=hiring_start_at",
            recordA.job_application.job_seeker,
            recordZ.job_application.job_seeker,
        )

        # Zzzzz after Aaaaa
        self._check_employee_record_order(
            self.url + "?status=READY&order=name",
            recordA.job_application.job_seeker,
            recordZ.job_application.job_seeker,
        )
        self._check_employee_record_order(
            self.url + "?status=READY&order=-name",
            recordZ.job_application.job_seeker,
            recordA.job_application.job_seeker,
        )
