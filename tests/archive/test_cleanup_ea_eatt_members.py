import re

import httpx
import pytest
from django.core.management import call_command

from itou.archive.models import AnonymizedProfessional
from itou.companies.enums import CompanyKind
from itou.companies.models import Company, CompanyMembership
from itou.users.models import NirModificationRequest, User
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.employee_record.factories import EmployeeRecordTransitionLogFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerFactory


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def brevo_api_key_fixture(settings):
    settings.BREVO_API_KEY = "BREVO_API_KEY"


@pytest.fixture(autouse=True)
def respx_delete_mock(respx_mock, settings):
    respx_mock.delete(url__regex=re.compile(f"^{re.escape(settings.BREVO_API_URL)}/contacts/.*")).mock(
        return_value=httpx.Response(status_code=204)
    )


class TestCleanupEaEattMembers:
    def test_user_only_in_ea_is_anonymized_and_deleted(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EA)
        user_id = membership.user_id

        call_command("cleanup_ea_eatt_members", wet_run=True)

        assert not User.objects.filter(id=user_id).exists()
        assert AnonymizedProfessional.objects.count() == 1
        assert not CompanyMembership.include_inactive.filter(user_id=user_id).exists()

    def test_user_only_in_inactive_eatt_is_anonymized(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EATT, is_active=False)
        user_id = membership.user_id

        call_command("cleanup_ea_eatt_members", wet_run=True)

        assert not User.objects.filter(id=user_id).exists()
        assert AnonymizedProfessional.objects.count() == 1

    def test_user_with_other_company_is_only_detached(self):
        user_membership = CompanyMembershipFactory(company__kind=CompanyKind.EA)
        user = user_membership.user
        other = CompanyMembershipFactory(user=user, company__kind=CompanyKind.ACI)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        assert User.objects.filter(id=user.id).exists()
        assert AnonymizedProfessional.objects.count() == 0
        assert not CompanyMembership.include_inactive.filter(user=user, company__kind=CompanyKind.EA).exists()
        assert CompanyMembership.include_inactive.filter(id=other.id).exists()

    def test_user_with_prescriber_membership_is_only_detached(self):
        ea_membership = CompanyMembershipFactory(company__kind=CompanyKind.EA)
        user = ea_membership.user
        PrescriberMembershipFactory(user=user)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        assert User.objects.filter(id=user.id).exists()
        assert AnonymizedProfessional.objects.count() == 0
        assert not CompanyMembership.include_inactive.filter(user=user).exists()

    def test_user_with_institution_membership_is_only_detached(self):
        ea_membership = CompanyMembershipFactory(company__kind=CompanyKind.EA)
        user = ea_membership.user
        InstitutionMembershipFactory(user=user)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        assert User.objects.filter(id=user.id).exists()
        assert AnonymizedProfessional.objects.count() == 0
        assert not CompanyMembership.include_inactive.filter(user=user).exists()

    def test_user_with_non_cascade_relation_is_anonymized_without_deletion(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EA, user__email="pro@example.com")
        user = membership.user
        JobApplicationFactory(sender=user, sent_by_prescriber_alone=True)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        user.refresh_from_db()
        assert user.is_active is False
        assert user.email is None
        assert user.phone == ""
        assert AnonymizedProfessional.objects.count() == 0

    def test_user_with_archived_job_application_is_anonymized_without_deletion(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EA, user__email="pro@example.com")
        user = membership.user
        job_app = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            archived_at="2025-01-01T00:00:00Z",
            archived_by=user,
        )

        call_command("cleanup_ea_eatt_members", wet_run=True)

        user.refresh_from_db()
        assert user.is_active is False
        assert user.email is None
        assert AnonymizedProfessional.objects.count() == 0
        job_app.refresh_from_db()
        assert job_app.archived_by_id == user.id

    def test_user_with_nir_modification_request_is_anonymized_without_deletion(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EA, user__email="pro@example.com")
        user = membership.user
        job_seeker = JobSeekerFactory()
        NirModificationRequest.objects.create(
            jobseeker_profile=job_seeker.jobseeker_profile,
            nir="269054958815780",
            requested_by=user,
        )

        call_command("cleanup_ea_eatt_members", wet_run=True)

        user.refresh_from_db()
        assert user.is_active is False
        assert user.email is None
        assert AnonymizedProfessional.objects.count() == 0
        assert NirModificationRequest.objects.filter(requested_by=user).exists()

    def test_user_with_employee_record_transition_log_is_anonymized_without_deletion(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EA, user__email="pro@example.com")
        user = membership.user
        EmployeeRecordTransitionLogFactory(user=user)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        user.refresh_from_db()
        assert user.is_active is False
        assert user.email is None
        assert AnonymizedProfessional.objects.count() == 0

    def test_dry_run_makes_no_changes(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EA)
        user_id = membership.user_id

        call_command("cleanup_ea_eatt_members")

        assert User.objects.filter(id=user_id).exists()
        assert AnonymizedProfessional.objects.count() == 0
        assert CompanyMembership.include_inactive.filter(user_id=user_id).exists()

    def test_ea_eatt_companies_are_blocked_and_memberships_removed(self):
        ea = CompanyFactory(kind=CompanyKind.EA, block_job_applications=False)
        eatt = CompanyFactory(kind=CompanyKind.EATT, block_job_applications=False)
        # Memberships that will be cascaded by anonymization (user-only-EA).
        CompanyMembershipFactory(company=ea)
        CompanyMembershipFactory(company=eatt)
        # Membership for a user who also has a non-EA membership: gets explicitly detached.
        mixed = CompanyMembershipFactory(company=ea)
        CompanyMembershipFactory(user=mixed.user, company__kind=CompanyKind.ACI)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        ea.refresh_from_db()
        eatt.refresh_from_db()
        assert ea.block_job_applications is True
        assert ea.job_applications_blocked_at is not None
        assert eatt.block_job_applications is True
        assert not CompanyMembership.include_inactive.filter(
            company__kind__in=[CompanyKind.EA, CompanyKind.EATT]
        ).exists()
        assert Company.unfiltered_objects.filter(kind__in=[CompanyKind.EA, CompanyKind.EATT]).count() == 2

    def test_user_with_inactive_ea_and_active_non_ea_is_only_detached(self):
        ea_membership = CompanyMembershipFactory(company__kind=CompanyKind.EA, is_active=False)
        user = ea_membership.user
        other = CompanyMembershipFactory(user=user, company__kind=CompanyKind.ACI, is_active=True)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        assert User.objects.filter(id=user.id).exists()
        assert AnonymizedProfessional.objects.count() == 0
        assert not CompanyMembership.include_inactive.filter(user=user, company__kind=CompanyKind.EA).exists()
        assert CompanyMembership.include_inactive.filter(id=other.id).exists()

    def test_non_ea_eatt_company_is_not_blocked(self):
        aci = CompanyFactory(kind=CompanyKind.ACI, block_job_applications=False)
        CompanyMembershipFactory(company=aci)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        aci.refresh_from_db()
        assert aci.block_job_applications is False
        assert aci.job_applications_blocked_at is None

    def test_already_anonymized_user_rerun_is_idempotent(self):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.EA, user__email="pro@example.com")
        user_id = membership.user_id
        JobApplicationFactory(sender=membership.user, sent_by_prescriber_alone=True)

        call_command("cleanup_ea_eatt_members", wet_run=True)
        call_command("cleanup_ea_eatt_members", wet_run=True)

        user = User.objects.get(id=user_id)
        assert user.is_active is False
        assert user.email is None

    def test_no_ea_eatt_users_is_noop(self, caplog):
        CompanyMembershipFactory(company__kind=CompanyKind.ACI)

        call_command("cleanup_ea_eatt_members", wet_run=True)

        assert AnonymizedProfessional.objects.count() == 0
        assert "EA/EATT cleanup done: anonymized=0 detached=0" in caplog.messages

    def test_batches_process_all_users(self):
        memberships = CompanyMembershipFactory.create_batch(5, company__kind=CompanyKind.EA)
        user_ids = [m.user_id for m in memberships]

        call_command("cleanup_ea_eatt_members", wet_run=True, batch_size=2)

        assert not User.objects.filter(id__in=user_ids).exists()
        assert AnonymizedProfessional.objects.count() == 5
