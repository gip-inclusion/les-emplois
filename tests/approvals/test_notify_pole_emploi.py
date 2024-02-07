import datetime
import io
import json
from unittest.mock import patch

import httpx
import respx
from django.core import management
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.models import Approval, CancelledApproval
from itou.companies.enums import CompanyKind, siae_kind_to_pe_type_siae
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.apis import enums as api_enums
from itou.utils.mocks.pole_emploi import (
    API_MAJPASS_RESULT_ERROR,
    API_MAJPASS_RESULT_OK,
    API_RECHERCHE_MANY_RESULTS,
    API_RECHERCHE_RESULT_KNOWN,
)
from tests.approvals.factories import ApprovalFactory, CancelledApprovalFactory, PoleEmploiApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


@override_settings(
    API_ESD={
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
class ApprovalNotifyPoleEmploiIntegrationTest(TestCase):
    def setUp(self):
        super().setUp()
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
        )

    def test_invalid_job_seeker_for_pole_emploi(self):
        """
        Error case: our job seeker is not valid (from PoleEmploi’s point of view: here, the NIR is missing)
         - We do not even call the APIs
         - no entry should be added to the notification log database
        """
        approval = ApprovalFactory(user__jobseeker_profile__nir="", with_jobapplication=True)
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_pending"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code == "MISSING_USER_DATA"

    def test_invalid_job_application(self):
        approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__state=JobApplicationWorkflow.STATE_CANCELLED,
        )
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_pending"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code == "NO_JOB_APPLICATION"

    @respx.mock
    @freeze_time("2021-06-21")
    def test_notification_accepted_nominal(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company__kind=CompanyKind.ACI,
        )
        approval.notify_pole_emploi()
        approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": approval.start_at.isoformat(),
            "dateFinPassIAE": approval.end_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": approval.number,
            "numSIRETsiae": approval.jobapplication_set.first().to_company.siret,
            "origineCandidature": "PRES",
            "statutReponsePassIAE": "A",
            "typeSIAE": 836,
        }
        assert approval.pe_notification_status == "notification_success"
        assert approval.pe_notification_time == timezone.now()
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None
        approval.user.jobseeker_profile.refresh_from_db()
        assert approval.user.jobseeker_profile.pe_obfuscated_nir == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"
        assert approval.user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
            2021, 6, 21, 0, 0, 0, tzinfo=datetime.timezone.utc
        )

    @respx.mock
    def test_notification_accepted_with_id_national(self):
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company__kind=CompanyKind.ACI,
        )
        approval.user.jobseeker_profile.pe_obfuscated_nir = "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"
        approval.user.jobseeker_profile.save()
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": approval.start_at.isoformat(),
            "dateFinPassIAE": approval.end_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": approval.number,
            "numSIRETsiae": approval.jobapplication_set.first().to_company.siret,
            "origineCandidature": "PRES",
            "statutReponsePassIAE": "A",
            "typeSIAE": 836,
        }
        assert approval.pe_notification_status == "notification_success"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_accepted_with_prescriber_organization(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company__kind=CompanyKind.ACI,
            with_jobapplication__sent_by_authorized_prescriber_organisation=True,
            with_jobapplication__sender_prescriber_organization__kind=PrescriberOrganizationKind.CAF,
        )
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": approval.start_at.isoformat(),
            "dateFinPassIAE": approval.end_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": approval.number,
            "numSIRETsiae": approval.jobapplication_set.first().to_company.siret,
            "origineCandidature": "PRES",
            "statutReponsePassIAE": "A",
            "typeSIAE": 836,
            "typologiePrescripteur": "CAF",
        }
        assert approval.pe_notification_status == "notification_success"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_accepted_with_sensitive_prescriber_organization(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        approval = ApprovalFactory(
            with_jobapplication=True,
            with_jobapplication__to_company__kind=CompanyKind.ACI,
            with_jobapplication__sent_by_authorized_prescriber_organisation=True,
            with_jobapplication__sender_prescriber_organization__kind=PrescriberOrganizationKind.SPIP,
        )
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": approval.start_at.isoformat(),
            "dateFinPassIAE": approval.end_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": approval.number,
            "numSIRETsiae": approval.jobapplication_set.first().to_company.siret,
            "origineCandidature": "PRES",
            "statutReponsePassIAE": "A",
            "typeSIAE": 836,
            "typologiePrescripteur": "Autre",
        }
        assert approval.pe_notification_status == "notification_success"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_stays_pending_if_approval_starts_after_today(self):
        now = timezone.now()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        tomorrow = (now + datetime.timedelta(days=1)).date()
        approval = ApprovalFactory(start_at=tomorrow)
        with freeze_time() as frozen_now, self.assertLogs("itou.approvals.models") as logs:
            approval.notify_pole_emploi()
        assert (
            f"notify_pole_emploi approval={approval} "
            f"start_at={approval.start_at} "
            f"starts after today={now.date()}" in logs.output[0]
        )
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_pending"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code == "STARTS_IN_FUTURE"

    @respx.mock
    def test_notification_goes_to_retry_if_there_is_a_timeout(self):
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").mock(
            side_effect=httpx.ConnectTimeout
        )
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker, with_jobapplication=True)
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_should_retry"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_goes_to_error_if_something_goes_wrong_with_rech_individu(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_MANY_RESULTS
        )
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker, with_jobapplication=True)
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_error"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint == "rech_individu"
        assert approval.pe_notification_exit_code == "S002"

    @respx.mock
    def test_notification_goes_to_error_if_something_goes_wrong_with_maj_pass(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_ERROR)
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker, with_jobapplication=True)
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_error"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint == "maj_pass"
        assert approval.pe_notification_exit_code == "S022"

    @respx.mock
    def test_notification_goes_to_error_if_missing_siae_kind(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_ERROR)
        job_seeker = JobSeekerFactory()
        company = CompanyFactory(kind="FOO")  # unknown kind
        approval = ApprovalFactory(user=job_seeker)
        JobApplicationFactory(to_company=company, approval=approval, state=JobApplicationWorkflow.STATE_ACCEPTED)
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_error"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code == "INVALID_SIAE_KIND"

    @respx.mock
    def test_notification_goes_to_pending_if_job_application_is_not_accepted(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_ERROR)
        job_seeker = JobSeekerFactory()
        company = CompanyFactory(kind="FOO")  # unknown kind
        approval = ApprovalFactory(user=job_seeker)
        JobApplicationFactory(to_company=company, approval=approval, state=JobApplicationWorkflow.STATE_POSTPONED)
        with freeze_time() as frozen_now:
            approval.notify_pole_emploi()
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_pending"
        assert approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code == "NO_JOB_APPLICATION"

    @respx.mock
    @freeze_time("2021-06-21")
    def test_notification_use_origin_values(self):
        now = timezone.now()
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        job_seeker = JobSeekerFactory()
        siae = CompanyFactory(kind="FOO")  # unknown kind
        approval = ApprovalFactory(user=job_seeker, with_origin_values=True, origin_siae_kind=CompanyKind.ETTI)
        JobApplicationFactory(to_company=siae, approval=approval, state=JobApplicationWorkflow.STATE_ACCEPTED)
        approval.notify_pole_emploi()
        approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": approval.start_at.isoformat(),
            "dateFinPassIAE": approval.end_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": approval.number,
            "numSIRETsiae": approval.origin_siae_siret,
            "origineCandidature": "EMPL",
            "statutReponsePassIAE": "A",
            "typeSIAE": 839,  # value for ETTI
        }
        assert approval.pe_notification_status == "notification_success"
        assert approval.pe_notification_time == now
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None
        approval.user.jobseeker_profile.refresh_from_db()
        assert approval.user.jobseeker_profile.pe_obfuscated_nir == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"
        assert approval.user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
            2021, 6, 21, 0, 0, 0, tzinfo=datetime.timezone.utc
        )


@override_settings(
    API_ESD={
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
class CancelledApprovalNotifyPoleEmploiIntegrationTest(TestCase):
    def setUp(self):
        super().setUp()
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
        )

    def test_invalid_job_seeker_for_pole_emploi(self):
        """
        Error case: our job seeker is not valid (from PoleEmploi’s point of view: here, the NIR is missing)
         - We do not even call the APIs
         - no entry should be added to the notification log database
        """
        cancelled_approval = CancelledApprovalFactory(user_nir="")
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        assert cancelled_approval.pe_notification_status == "notification_pending"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code == "MISSING_USER_DATA"

    @respx.mock
    def test_notification_accepted_nominal(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        cancelled_approval = CancelledApprovalFactory(origin_siae_kind=CompanyKind.EI)
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": cancelled_approval.start_at.isoformat(),
            "dateFinPassIAE": cancelled_approval.start_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": cancelled_approval.number,
            "numSIRETsiae": cancelled_approval.origin_siae_siret,
            "origineCandidature": "EMPL",
            "statutReponsePassIAE": "A",
            "typeSIAE": 838,
        }
        assert cancelled_approval.pe_notification_status == "notification_success"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_accepted_with_id_national(self):
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        cancelled_approval = CancelledApprovalFactory(
            origin_siae_kind=CompanyKind.ACI, user_id_national_pe="ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"
        )
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": cancelled_approval.start_at.isoformat(),
            "dateFinPassIAE": cancelled_approval.start_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": cancelled_approval.number,
            "numSIRETsiae": cancelled_approval.origin_siae_siret,
            "origineCandidature": "EMPL",
            "statutReponsePassIAE": "A",
            "typeSIAE": 836,
        }
        assert cancelled_approval.pe_notification_status == "notification_success"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_accepted_with_prescriber_organization(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        cancelled_approval = CancelledApprovalFactory(
            origin_siae_kind=CompanyKind.ACI,
            origin_sender_kind=SenderKind.PRESCRIBER,
            origin_prescriber_organization_kind=PrescriberOrganizationKind.CAF,
        )
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": cancelled_approval.start_at.isoformat(),
            "dateFinPassIAE": cancelled_approval.start_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": cancelled_approval.number,
            "numSIRETsiae": cancelled_approval.origin_siae_siret,
            "origineCandidature": "PRES",
            "statutReponsePassIAE": "A",
            "typeSIAE": 836,
            "typologiePrescripteur": "CAF",
        }
        assert cancelled_approval.pe_notification_status == "notification_success"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_accepted_with_sensitive_prescriber_organization(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        cancelled_approval = CancelledApprovalFactory(
            origin_siae_kind=CompanyKind.ACI,
            origin_sender_kind=SenderKind.PRESCRIBER,
            origin_prescriber_organization_kind=PrescriberOrganizationKind.SPIP,
        )
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": cancelled_approval.start_at.isoformat(),
            "dateFinPassIAE": cancelled_approval.start_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": cancelled_approval.number,
            "numSIRETsiae": cancelled_approval.origin_siae_siret,
            "origineCandidature": "PRES",
            "statutReponsePassIAE": "A",
            "typeSIAE": 836,
            "typologiePrescripteur": "Autre",
        }
        assert cancelled_approval.pe_notification_status == "notification_success"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code is None

    @respx.mock
    @freeze_time()
    def test_notification_stays_pending_if_approval_starts_after_today(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        tomorrow = (timezone.now() + datetime.timedelta(days=1)).date()
        cancelled_approval = CancelledApprovalFactory(start_at=tomorrow)
        with self.assertLogs("itou.approvals.models") as logs:
            cancelled_approval.notify_pole_emploi()
        assert (
            f"notify_pole_emploi cancelledapproval={cancelled_approval} "
            f"start_at={cancelled_approval.start_at} "
            f"starts after today={timezone.now().date()}" in logs.output[0]
        )
        cancelled_approval.refresh_from_db()
        assert cancelled_approval.pe_notification_status == "notification_pending"
        assert cancelled_approval.pe_notification_time == timezone.now()
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code == "STARTS_IN_FUTURE"

    @respx.mock
    def test_notification_goes_to_retry_if_there_is_a_timeout(self):
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").mock(
            side_effect=httpx.ConnectTimeout
        )
        cancelled_approval = CancelledApprovalFactory()
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        assert cancelled_approval.pe_notification_status == "notification_should_retry"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code is None

    @respx.mock
    def test_notification_goes_to_error_if_something_goes_wrong_with_rech_individu(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_MANY_RESULTS
        )
        cancelled_approval = CancelledApprovalFactory()
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        assert cancelled_approval.pe_notification_status == "notification_error"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint == "rech_individu"
        assert cancelled_approval.pe_notification_exit_code == "S002"

    @respx.mock
    def test_notification_goes_to_error_if_something_goes_wrong_with_maj_pass(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_ERROR)
        cancelled_approval = CancelledApprovalFactory()
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        assert cancelled_approval.pe_notification_status == "notification_error"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint == "maj_pass"
        assert cancelled_approval.pe_notification_exit_code == "S022"

    @respx.mock
    def test_notification_goes_to_error_if_missing_siae_kind(self):
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_ERROR)
        cancelled_approval = CancelledApprovalFactory(origin_siae_kind="FOO")  # unknown kind
        with freeze_time() as frozen_now:
            cancelled_approval.notify_pole_emploi()
        cancelled_approval.refresh_from_db()
        assert cancelled_approval.pe_notification_status == "notification_error"
        assert cancelled_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert cancelled_approval.pe_notification_endpoint is None
        assert cancelled_approval.pe_notification_exit_code == "INVALID_SIAE_KIND"


class ApprovalsSendToPeManagementTestCase(TestCase):
    @patch.object(CancelledApproval, "notify_pole_emploi")
    @patch.object(Approval, "notify_pole_emploi")
    @patch("itou.approvals.management.commands.send_approvals_to_pe.sleep")
    # smaller batch to ease testing
    @patch("itou.approvals.management.commands.send_approvals_to_pe.MAX_APPROVALS_PER_RUN", 10)
    def test_invalid_job_seeker_for_pole_emploi(self, sleep_mock, notify_mock, cancelled_notify_mock):
        stdout = io.StringIO()
        # create ignored Approvals, will not even be counted in the batch. the cron will wait for
        # the database to have the necessary job application, nir, or start date to fetch them.
        no_jobapp = ApprovalFactory(with_jobapplication=False)
        missing_user_data1 = ApprovalFactory(user__jobseeker_profile__nir="")
        missing_user_data2 = ApprovalFactory(user__birthdate=None)
        future = ApprovalFactory(start_at=datetime.datetime.today().date() + datetime.timedelta(days=1))

        # Create CancelledApproval
        cancelled_approval_future = CancelledApprovalFactory(
            start_at=datetime.datetime.today().date() + datetime.timedelta(days=1)
        )
        cancelled_approvals = [
            CancelledApprovalFactory(start_at=datetime.datetime.today().date() - datetime.timedelta(days=i))
            for i in range(10)
        ]

        # other approvals
        error_approval = ApprovalFactory(
            start_at=datetime.datetime.today().date() - datetime.timedelta(days=2),
            with_jobapplication=True,
            pe_notification_status=api_enums.PEApiNotificationStatus.ERROR,
            pe_notification_endpoint=api_enums.PEApiEndpoint.RECHERCHE_INDIVIDU,
        )
        error_approval_with_obfuscated_nir = ApprovalFactory(
            start_at=datetime.datetime.today().date() - datetime.timedelta(days=2),
            with_jobapplication=True,
            pe_notification_status=api_enums.PEApiNotificationStatus.ERROR,
            pe_notification_endpoint=api_enums.PEApiEndpoint.RECHERCHE_INDIVIDU,
            user__jobseeker_profile__pe_obfuscated_nir="something",
        )
        retry_approval = ApprovalFactory(
            start_at=datetime.datetime.today().date() - datetime.timedelta(days=1),
            with_jobapplication=True,
            pe_notification_status="notification_should_retry",
        )
        pending_approval = ApprovalFactory(with_jobapplication=True)
        management.call_command(
            "send_approvals_to_pe",
            wet_run=True,
            delay=3,
            stdout=stdout,
        )
        assert stdout.getvalue().split("\n") == [
            "approvals needing to be sent count=3, batch count=10",
            f"approvals={pending_approval} start_at={pending_approval.start_at.isoformat()} "
            "pe_state=notification_ready",
            f"approvals={retry_approval} start_at={retry_approval.start_at.isoformat()} "
            "pe_state=notification_should_retry",
            f"approvals={error_approval_with_obfuscated_nir} "
            f"start_at={error_approval_with_obfuscated_nir.start_at.isoformat()} pe_state=notification_ready",
            "cancelled approvals needing to be sent count=10, batch count=7",
        ] + [
            f"cancelled_approval={cancelled_approval} start_at={cancelled_approval.start_at.isoformat()} "
            "pe_state=notification_ready"
            for cancelled_approval in cancelled_approvals[:7]
        ] + [
            "",
        ]
        sleep_mock.assert_called_with(3)
        assert sleep_mock.call_count == 10
        assert notify_mock.call_count == 3
        assert cancelled_notify_mock.call_count == 7
        for approval in [no_jobapp, missing_user_data1, missing_user_data2, future, cancelled_approval_future]:
            approval.refresh_from_db()
            assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING
        # Since the notify_pole_emploi have been mocked, the READY/SHOULD_RETRY approvals kept their statuses
        retry_approval.refresh_from_db()
        assert retry_approval.pe_notification_status == api_enums.PEApiNotificationStatus.SHOULD_RETRY
        error_approval.refresh_from_db()
        assert error_approval.pe_notification_status == api_enums.PEApiNotificationStatus.ERROR
        for approval in [pending_approval, error_approval_with_obfuscated_nir, *cancelled_approvals]:
            approval.refresh_from_db()
            assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.READY


@override_settings(
    API_ESD={
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
class PoleEmploiApprovalNotifyPoleEmploiIntegrationTest(TestCase):
    @respx.mock
    def test_notification_accepted_nominal(self):
        respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
        )
        respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
            200, json=API_RECHERCHE_RESULT_KNOWN
        )
        respx.post("https://pe.fake/maj-pass-iae/v1/passIAE/miseAjour").respond(200, json=API_MAJPASS_RESULT_OK)
        pe_approval = PoleEmploiApprovalFactory(
            nir="FOOBAR2000", siae_kind=CompanyKind.ACI.value
        )  # avoid the OPCS, not mapped yet
        with freeze_time() as frozen_now:
            pe_approval.notify_pole_emploi()
        pe_approval.refresh_from_db()
        payload = json.loads(respx.calls.last.request.content)
        assert payload == {
            "dateDebutPassIAE": pe_approval.start_at.isoformat(),
            "dateFinPassIAE": pe_approval.end_at.isoformat(),
            "idNational": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
            "numPassIAE": pe_approval.number,
            "numSIRETsiae": pe_approval.siae_siret,
            "origineCandidature": "PRES",
            "statutReponsePassIAE": "A",
            "typeSIAE": siae_kind_to_pe_type_siae(pe_approval.siae_kind),
            "typologiePrescripteur": "PE",
        }
        assert pe_approval.pe_notification_status == "notification_success"
        assert pe_approval.pe_notification_time == frozen_now().replace(tzinfo=datetime.UTC)
        assert pe_approval.pe_notification_endpoint is None
        assert pe_approval.pe_notification_exit_code is None
