import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.users import admin
from itou.users.models import JobSeekerProfile, User
from tests.companies.factories import CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerFactory


def test_search(admin_client):
    user = JobSeekerFactory()
    other_user = JobSeekerFactory()

    response = admin_client.get(reverse("admin:users_user_changelist") + f"?q={user.public_id}")
    assertContains(response, user.email)
    assertNotContains(response, other_user.email)


def test_filter():
    js_certified = JobSeekerFactory()
    js_certified.jobseeker_profile.pe_obfuscated_nir = "PRINCEOFBELAIR"
    js_certified.jobseeker_profile.save()

    js_non_certified = JobSeekerFactory(jobseeker_profile__pe_obfuscated_nir=None)

    filter = admin.IsPECertifiedFilter(
        None,
        {"is_pe_certified": ["yes"]},
        JobSeekerProfile,
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == [js_certified.jobseeker_profile]

    filter = admin.IsPECertifiedFilter(
        None,
        {"is_pe_certified": ["no"]},
        JobSeekerProfile,
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == [js_non_certified.jobseeker_profile]

    filter = admin.IsPECertifiedFilter(
        None,
        {},
        JobSeekerProfile,
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert set(profiles) == {js_certified.jobseeker_profile, js_non_certified.jobseeker_profile}


def test_get_fields_to_transfer_for_job_seekers():
    # Get list of fields pointing to the User models
    relation_fields = {field for field in User._meta.get_fields() if field.is_relation and not field.many_to_one}
    fields_to_ignore = {
        "administrativecriteria",  # AdministrativeCriteria.created_by
        "approval",  # Approval.created_by
        "approval_manually_delivered",  # JobApplication.approval_manually_delivered_by
        "approval_manually_refused",  # JobApplication.approval_manually_refused_by
        "approvals_suspended_set",  # Suspension.created_by
        "auth_token",  # rest_framework.authtoken.models.Token.user
        "authorization_status_set",  # PrescriberOrganization.authorization_updated_by
        "company",  # Company.members
        "created_prescriber_organization_set",  # PrescriberOrganization.created_by
        "created_company_set",  # Siae.created_by
        "created_follow_up_groups",  # gps.FollowUpGroupMembership.creator: creator of a follow up group of GPS
        "eligibilitydiagnosis",  # EligibilityDiagnosis.author
        "emailaddress",  # allauth.account.models.EmailAddress.user
        "externaldataimport",  # ExternalDataImport.user: this seems largely unused
        "follow_up_group",  # gps.FollowUpGroup: do I have a GPS follow group as a jobseeker
        "follow_up_groups",  # gps.FollowUpGroupMembership.member: followup groups membership
        "follow_up_groups_member",  # gps.FollowUpGroup.member: followup groups
        "geiqadministrativecriteria",  # GEIQAdministrativeCriteria.created_by
        "geiqeligibilitydiagnosis",  # GEIQEligibilityDiagnosis.author
        "groups",  # django.contrib.auth.models.Group
        "institution",  # Institution.members
        "institution_invitations",  # LaborInspectorInvitation.sender
        "institutionmembership",  # InstitutionMembership.user
        "job_applications_sent",  # JobApplication.sender
        "jobapplication",  # JobApplication.transferred_by
        "jobapplicationtransitionlog",  # JobApplicationTransitionLog.user
        "jobseeker_profile",  # JobSeekerProfile.user: the target already has one
        "jobseekerexternaldata",  # JobSeekerExternalData.user: this seems largely unused
        "logentry",  # django.contrib.admin.models.LogEntry.user
        "prescriber_org_invitations",  # PrescriberWithOrgInvitation.sender
        "prescribermembership",  # PrescriberMembership.user
        "prescriberorganization",  # PrescriberOrganization.members
        "prolongationrequest_processed",  # ProlongationRequest.processed_by
        "prolongationrequests_created",  # ProlongationRequest.created_by
        "prolongationrequests_declared",  # ProlongationRequest.declared_by
        "prolongationrequests_updated",  # ProlongationRequest.updated_by
        "prolongationrequests_validated",  # ProlongationRequest.validated_by
        "prolongations_created",  # Prolongation.created_by
        "prolongations_declared",  # Prolongation.declared_by
        "prolongations_updated",  # Prolongation.updated_by
        "prolongations_validated",  # Prolongation.validated_by
        "reactivated_siae_convention_set",  # SiaeConvention.reactivated_by
        "reviewed_geiq_assessment_set",  # ImplementationAssessment.reviewed_by
        "company_invitations",  # EmployerInvitation.sender
        "companymembership",  # CompanyMembership.user
        "submitted_geiq_assessment_set",  # ImplementationAssessment.submitted_by
        "suspension",  # Suspension.updated_by
        "updated_institutionmembership_set",  # InstitutionMembership.updated_by
        "updated_prescribermembership_set",  # PrescriberMembership.updated_by
        "updated_companymembership_set",  # CompanyMembership.updated_by
        "user",  # User.created_by
        "user_permissions",  # django.contrib.auth.models.Permission
        "notification_settings",  # NotificationSettings.user
        "rdvi_invitation_requests",  # InvitationRequest.job_seeker
        "rdvi_participations",  # Participation.job_seeker
        "rdvi_appointments",  # Appointment.company
    }
    fields_to_transfer = {f.name for f in admin.get_fields_to_transfer_for_job_seekers()}
    # Check that all fields have been accounted for
    # If this test fails:
    # - either a new relation has been added
    #   (and the dev must decide if it needs to be transfered or ignored in the transfer)
    # - either an existing relation has been dropped (and the relation can be removed from the relevant list)
    assert not fields_to_transfer & fields_to_ignore, fields_to_transfer & fields_to_ignore
    assert {f.name for f in relation_fields} == fields_to_transfer | fields_to_ignore


@pytest.mark.parametrize(
    "membership_factory",
    [
        PrescriberMembershipFactory,
        CompanyMembershipFactory,
        InstitutionMembershipFactory,
    ],
)
def test_admin_membership(admin_client, membership_factory):
    membership = membership_factory()
    response = admin_client.get(reverse("admin:users_user_change", args=(membership.user_id,)))
    assert response.status_code == 200
