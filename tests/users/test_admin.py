import random

from django.contrib.auth import get_user
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertQuerySetEqual, assertRedirects

from itou.users import admin
from itou.users.enums import IdentityCertificationAuthorities, IdentityProvider
from itou.users.models import IdentityCertification, JobSeekerProfile, NirModificationRequest, User
from tests.users.factories import EmployerFactory, JobSeekerFactory, JobSeekerProfileFactory, PrescriberFactory
from tests.utils.testing import normalize_fields_history


def test_search(admin_client):
    user = JobSeekerFactory()
    other_user = JobSeekerFactory()

    response = admin_client.get(reverse("admin:users_user_changelist") + f"?q={user.public_id}")
    assertContains(response, user.email)
    assertNotContains(response, other_user.email)


def test_filter():
    ft_certified = JobSeekerFactory(first_name="FT", last_name="Certified")
    IdentityCertification.objects.create(
        certifier=IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE,
        jobseeker_profile=ft_certified.jobseeker_profile,
    )
    api_particulier_certified = JobSeekerFactory(first_name="API Particulier", last_name="Certified")
    IdentityCertification.objects.create(
        certifier=IdentityCertificationAuthorities.API_PARTICULIER,
        jobseeker_profile=api_particulier_certified.jobseeker_profile,
    )
    not_certified = JobSeekerFactory(first_name="NOT", last_name="Certified")

    filter = admin.CertifierFilter(
        None,
        {"certifier": [IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE]},
        JobSeekerProfile,
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == [ft_certified.jobseeker_profile]

    filter = admin.CertifierFilter(
        None,
        {"certifier": [IdentityCertificationAuthorities.API_PARTICULIER]},
        JobSeekerProfile,
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == [api_particulier_certified.jobseeker_profile]

    filter = admin.CertifierFilter(
        None,
        {"certifier": ["not_certified"]},
        JobSeekerProfile,
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == [not_certified.jobseeker_profile]

    filter = admin.CertifierFilter(
        None,
        {},
        JobSeekerProfile,
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert set(profiles) == {
        ft_certified.jobseeker_profile,
        api_particulier_certified.jobseeker_profile,
        not_certified.jobseeker_profile,
    }


def test_get_fields_to_transfer_for_job_seekers():
    # Get list of fields pointing to the User models
    relation_fields = {field for field in User._meta.get_fields() if field.is_relation and not field.many_to_one}
    fields_to_ignore = {
        "activated_services",  # ActivatedService.user,
        "approval",  # Approval.created_by
        "approval_manually_delivered",  # JobApplication.approval_manually_delivered_by
        "approval_manually_refused",  # JobApplication.approval_manually_refused_by
        "approvals_suspended_set",  # Suspension.created_by
        "auth_token",  # rest_framework.authtoken.models.Token.user
        "authorization_status_set",  # PrescriberOrganization.authorization_updated_by
        "contracts",  # Contract.job_seeker
        "company",  # Company.members
        "created_assessments",  # Assessment.created_by
        "created_prescriber_organization_set",  # PrescriberOrganization.created_by
        "created_company_set",  # Siae.created_by
        "created_follow_up_groups",  # gps.FollowUpGroupMembership.creator: creator of a follow up group of GPS
        "final_reviewed_assessments",  # Assessment.final_reviewed_by
        "eligibilitydiagnosis",  # EligibilityDiagnosis.author
        "emailaddress",  # allauth.account.models.EmailAddress.user
        "externaldataimport",  # ExternalDataImport.user: this seems largely unused
        "follow_up_group",  # gps.FollowUpGroup: do I have a GPS follow group as a jobseeker
        "follow_up_groups",  # gps.FollowUpGroupMembership.member: followup groups membership
        "follow_up_groups_member",  # gps.FollowUpGroup.member: followup groups
        "geiqeligibilitydiagnosis",  # GEIQEligibilityDiagnosis.author
        "groups",  # django.contrib.auth.models.Group
        "institution",  # Institution.members
        "institution_invitations",  # LaborInspectorInvitation.sender
        "institutionmembership",  # InstitutionMembership.user
        "job_applications_sent",  # JobApplication.sender, but might be replaced when transferring application
        # sent by the job seeker
        "jobapplication",  # JobApplication.transferred_by
        "jobapplicationcomment",  # JobApplicationComment.created_by
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
        "prolongationrequests_assigned",  # ProlongationRequest.assigned_to
        "prolongations_created",  # Prolongation.created_by
        "prolongations_declared",  # Prolongation.declared_by
        "prolongations_updated",  # Prolongation.updated_by
        "prolongations_validated",  # Prolongation.validated_by
        "reactivated_siae_convention_set",  # SiaeConvention.reactivated_by
        "reviewed_assessments",  # Assessment.reviewed_by
        "saved_searches",  # SavedSearch.user
        "submitted_assessments",  # Assessment.submitted_by
        "company_invitations",  # EmployerInvitation.sender
        "companymembership",  # CompanyMembership.user
        "suspension",  # Suspension.updated_by
        "totpdevice",  # TOTPDevice.user
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
    #   (and the dev must decide if it needs to be transferred or ignored in the transfer)
    # - either an existing relation has been dropped (and the relation can be removed from the relevant list)
    assert not fields_to_transfer & fields_to_ignore, fields_to_transfer & fields_to_ignore
    assert {f.name for f in relation_fields} == fields_to_transfer | fields_to_ignore


def test_change_email(admin_client, caplog):
    user = JobSeekerFactory(with_verified_email=True)
    response = admin_client.post(
        reverse("admin:users_user_change", kwargs={"object_id": user.pk}),
        {
            "username": user.username,
            "email": "new@mailinator.com",
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
            "approvals-TOTAL_FORMS": "0",
            "approvals-INITIAL_FORMS": "0",
            "approvals-MIN_NUM_FORMS": "0",
            "approvals-MAX_NUM_FORMS": "0",
            "emailaddress_set-TOTAL_FORMS": "0",
            "emailaddress_set-INITIAL_FORMS": "0",
            "emailaddress_set-MIN_NUM_FORMS": "0",
            "emailaddress_set-MAX_NUM_FORMS": "0",
            "eligibility_diagnoses-TOTAL_FORMS": "0",
            "eligibility_diagnoses-INITIAL_FORMS": "0",
            "eligibility_diagnoses-MIN_NUM_FORMS": "0",
            "eligibility_diagnoses-MAX_NUM_FORMS": "0",
            "geiq_eligibility_diagnoses-TOTAL_FORMS": "0",
            "geiq_eligibility_diagnoses-INITIAL_FORMS": "0",
            "geiq_eligibility_diagnoses-MIN_NUM_FORMS": "0",
            "geiq_eligibility_diagnoses-MAX_NUM_FORMS": "0",
            "job_applications-TOTAL_FORMS": "0",
            "job_applications-INITIAL_FORMS": "0",
            "job_applications-MIN_NUM_FORMS": "0",
            "job_applications-MAX_NUM_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
            "utils-pksupportremark-content_type-object_id-0-remark": "",
            "utils-pksupportremark-content_type-object_id-0-id": "",
            "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
            "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
            "_save": "Enregistrer",
        },
    )
    assertRedirects(response, reverse("admin:users_user_changelist"))
    assert f"Deleted 1 EmailAddress for user pk={user.pk}." in caplog.messages
    assert f"Created primary, verified EmailAddress for user pk={user.pk}." in caplog.messages
    user.refresh_from_db()
    assert user.email == "new@mailinator.com"
    assertQuerySetEqual(
        user.emailaddress_set.all(),
        [(user.pk, "new@mailinator.com", True, True)],
        transform=lambda emailaddress: (
            emailaddress.user_id,
            emailaddress.email,
            emailaddress.primary,
            emailaddress.verified,
        ),
    )


@freeze_time("2025-06-16")
def test_external_data_source_history(admin_client):
    user = JobSeekerFactory()
    user.is_pe_jobseeker = True
    user.update_external_data_source_history_field(IdentityProvider.FRANCE_CONNECT, "is_pe_jobseeker", True)
    user.save()
    response = admin_client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
    code = (
        "<pre><code>[{'created_at': '2025-06-16T00:00:00Z', 'field_name': 'is_pe_jobseeker',"
        " 'source': 'FC', 'value': True}]</code></pre>"
    )
    assertContains(response, code, html=True)


JOBSEEKERPROFILE_FORMSETS_PAYLOAD = {
    "identity_certifications-TOTAL_FORMS": "0",
    "identity_certifications-INITIAL_FORMS": "0",
    "identity_certifications-MIN_NUM_FORMS": "0",
    "identity_certifications-MAX_NUM_FORMS": "0",
    "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
    "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
    "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
    "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
    "utils-pksupportremark-content_type-object_id-0-remark": "",
    "utils-pksupportremark-content_type-object_id-0-id": "",
    "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
    "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
}


def test_change_asp_uid(admin_client):
    profile = JobSeekerProfileFactory(asp_uid="000000000000000000000000000000")

    admin_client.post(
        reverse("admin:users_jobseekerprofile_change", kwargs={"object_id": profile.pk}),
        {
            "_continue": "Enregistrer+et+continuer+les+modifications",
            "user": profile.user.pk,
            "asp_uid": "000000000000000000000000000001",
            "birthdate": profile.birthdate.isoformat(),
            "birth_place": "",
            "birth_country": "",
            "education_level": "",
            "nir": "",
            "lack_of_nir_reason": "",
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": "",
            "pole_emploi_since": "",
            "unemployed_since": "",
            "created_by_prescriber_organization": "",
            "has_rsa_allocation": "NON",
            "rsa_allocation_since": "",
            "ass_allocation_since": "",
            "aah_allocation_since": "",
            "are_allocation_since": "",
            "activity_bonus_since": "",
            "actor_met_for_business_creation": "",
            "mean_monthly_income_before_process": "",
            "eiti_contributions": "",
            "hexa_lane_number": "",
            "hexa_std_extension": "",
            "hexa_non_std_extension": "",
            "hexa_lane_name": "",
            "hexa_additional_address": "",
            **JOBSEEKERPROFILE_FORMSETS_PAYLOAD,
        },
    )
    profile.refresh_from_db()
    assert profile.asp_uid == "000000000000000000000000000001"
    assert normalize_fields_history(profile.fields_history) == [
        {
            "_context": {"request_id": "[REQUEST ID]", "user": get_user(admin_client).pk},
            "_timestamp": "[TIMESTAMP]",
            "before": {"asp_uid": "000000000000000000000000000000"},
            "after": {"asp_uid": "000000000000000000000000000001"},
        }
    ]


def test_nir_modification_request_changelist(admin_client):
    job_seekers = JobSeekerFactory.create_batch(2)
    nir_modification_requests = [
        NirModificationRequest(jobseeker_profile=job_seeker.jobseeker_profile, requested_by=EmployerFactory())
        for job_seeker in job_seekers
    ]
    NirModificationRequest.objects.bulk_create(nir_modification_requests)

    url = reverse("admin:users_nirmodificationrequest_changelist")
    response = admin_client.get(url)
    for nir_modification_request in nir_modification_requests:
        assertContains(response, nir_modification_request.jobseeker_profile.user.get_full_name())
        assertContains(response, nir_modification_request.requested_by.get_full_name())


def test_nir_modification_request_display_requested_by_kind(admin_client):
    job_seeker = JobSeekerFactory()
    (requested_by, display_kind) = random.choice(
        [(job_seeker, "candidat"), (EmployerFactory(), "employeur"), (PrescriberFactory(), "prescripteur")]
    )
    nir_modification_request = NirModificationRequest.objects.create(
        jobseeker_profile=job_seeker.jobseeker_profile, requested_by=requested_by
    )

    url = reverse("admin:users_nirmodificationrequest_change", args=[nir_modification_request.pk])
    response = admin_client.get(url)
    assertContains(response, f'<div class="readonly">{display_kind}</div>')


def test_change_display_with_pii(admin_client):
    job_seeker = JobSeekerFactory()
    response = admin_client.get(reverse("admin:users_user_change", kwargs={"object_id": job_seeker.pk}))
    assertContains(response, f"<h2>{job_seeker.display_with_pii}</h2>")
    response = admin_client.get(
        reverse("admin:users_jobseekerprofile_change", kwargs={"object_id": job_seeker.jobseeker_profile.pk})
    )
    assertContains(response, f"<h2>{job_seeker.display_with_pii}</h2>")


def test_change_birth_information(admin_client):
    profile = JobSeekerFactory(born_in_france=True, with_birth_place=True).jobseeker_profile

    response = admin_client.post(
        reverse("admin:users_jobseekerprofile_change", kwargs={"object_id": profile.pk}),
        {
            "_continue": "Enregistrer+et+continuer+les+modifications",
            "user": profile.user.pk,
            "asp_uid": profile.asp_uid,
            "birthdate": profile.birthdate,
            "birth_place": profile.birth_place.pk,
            "birth_country": "",
            "education_level": "",
            "nir": "",
            "lack_of_nir_reason": "",
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": "",
            "pole_emploi_since": "",
            "unemployed_since": "",
            "created_by_prescriber_organization": "",
            "has_rsa_allocation": "NON",
            "rsa_allocation_since": "",
            "ass_allocation_since": "",
            "aah_allocation_since": "",
            "are_allocation_since": "",
            "activity_bonus_since": "",
            "actor_met_for_business_creation": "",
            "mean_monthly_income_before_process": "",
            "eiti_contributions": "",
            "hexa_lane_number": "",
            "hexa_std_extension": "",
            "hexa_non_std_extension": "",
            "hexa_lane_name": "",
            "hexa_additional_address": "",
            **JOBSEEKERPROFILE_FORMSETS_PAYLOAD,
        },
    )
    assertContains(
        response, "La commune de naissance doit être spécifiée si et seulement si le pays de naissance est la France."
    )
