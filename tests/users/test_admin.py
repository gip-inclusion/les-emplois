import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.users import admin
from itou.users.models import JobSeekerProfile, User
from itou.utils.models import PkSupportRemark
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
    admin_active_membership = membership_factory()
    user = admin_active_membership.user
    active_membership = membership_factory(user=user, is_active=True, is_admin=False)
    inactive_membership = membership_factory(user=user, is_active=False, is_admin=False)
    url = reverse("admin:users_user_change", args=(user.pk,))
    response = admin_client.get(url)
    assert response.status_code == 200

    membership_field_name = active_membership._meta.get_field("user").remote_field.name

    post_data = {
        "username": user.username,
        "email": user.email,
        "last_login_0": "21/02/2025",
        "last_login_1": "09:46:54",
        "date_joined_0": "19/02/2025",
        "date_joined_1": "18:00:47",
        "initial-date_joined_0": "19/02/2025",
        "initial-date_joined_1": "18:00:47",
        "last_checked_at_0": "19/02/2025",
        "last_checked_at_1": "18:00:47",
        "initial-last_checked_at_0": "19/02/2025",
        "initial-last_checked_at_1": "18:00:47",
        "title": "",
        "phone": "",
        "address_line_1": "",
        "address_line_2": "",
        "post_code": "",
        "department": "",
        "city": "",
        "created_by": "",
        "emailaddress_set-TOTAL_FORMS": "0",
        "emailaddress_set-INITIAL_FORMS": "0",
        "emailaddress_set-MIN_NUM_FORMS": "0",
        "emailaddress_set-MAX_NUM_FORMS": "0",
        f"{membership_field_name}_set-TOTAL_FORMS": "3",
        f"{membership_field_name}_set-INITIAL_FORMS": "3",
        f"{membership_field_name}_set-MIN_NUM_FORMS": "0",
        f"{membership_field_name}_set-MAX_NUM_FORMS": "0",
        f"{membership_field_name}_set-0-id": admin_active_membership.pk,
        f"{membership_field_name}_set-0-user": user.pk,
        f"{membership_field_name}_set-1-id": active_membership.pk,
        f"{membership_field_name}_set-1-user": user.pk,
        f"{membership_field_name}_set-2-id": inactive_membership.pk,
        f"{membership_field_name}_set-2-user": user.pk,
        "job_applications_sent-TOTAL_FORMS": "0",
        "job_applications_sent-INITIAL_FORMS": "0",
        "job_applications_sent-MIN_NUM_FORMS": "0",
        "job_applications_sent-MAX_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-0-remark": "",
        "utils-pksupportremark-content_type-object_id-0-id": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
        "_save": "Enregistrer",
    }
    response = admin_client.post(url, data=post_data)
    assertRedirects(response, reverse("admin:users_user_changelist"))

    admin_active_membership.refresh_from_db()
    assert admin_active_membership.is_active is False
    assert admin_active_membership.is_admin is False
    active_membership.refresh_from_db()
    assert active_membership.is_active is False
    assert active_membership.is_admin is False
    inactive_membership.refresh_from_db()
    assert inactive_membership.is_active is False
    assert inactive_membership.is_admin is False

    user_content_type = ContentType.objects.get_for_model(User)
    user_remark = PkSupportRemark.objects.filter(content_type=user_content_type, object_id=user.pk).get()
    assert (
        f"Désactivation de {admin_active_membership} suite à la désactivation de l'utilisateur : "
        "is_active=True is_admin=True" in user_remark.remark
    )
    assert (
        f"Désactivation de {active_membership} suite à la désactivation de l'utilisateur : "
        "is_active=True is_admin=False" in user_remark.remark
    )
    assert f"Désactivation de {inactive_membership}" not in user_remark.remark
