from django.contrib.auth.models import Group, Permission

from itou.utils.command import BaseCommand


PERMS_ALL = {"add", "change", "delete", "view"}
PERMS_DELETE = {"delete", "view"}
PERMS_ADD = {"add", "change", "view"}
PERMS_EDIT = {"change", "view"}
PERMS_HIJACK = {"view", "hijack"}
PERMS_READ = {"view"}

# Permissions for specific staff actions
PERMS_EXPORT_FT_API_REJECTIONS = {"export_ft_api_rejections"}
PERMS_EXPORT_JOB_APPLICATIONS_UNKNOWN_TO_FT = {"export_job_applications_unknown_to_ft"}
PERMS_EXPORT_CTA = {"export_cta"}
PERMS_HANDLE_MANUAL_APPROVAL_REQUESTS = {"handle_manual_approval_requests"}
PERMS_MERGE_USERS = {"merge_users"}

# Authorized permissions for readonly groups
PERMS_READONLY = PERMS_READ | PERMS_EXPORT_CTA


def get_permissions_dict():
    # lazy-import necessary models. Better than using string since we can then use introspection
    # and tooling will help us with refactoring, dead code and models, etc.
    import allauth.account.models as account_models

    import itou.analytics.models as analytics_models
    import itou.approvals.models as approvals_models
    import itou.asp.models as asp_models
    import itou.cities.models as cities_models
    import itou.communications.models as communications_models
    import itou.companies.models as companies_models
    import itou.eligibility.models as eligibility_models
    import itou.emails.models as emails_models
    import itou.employee_record.models as employee_record_models
    import itou.external_data.models as external_data_models
    import itou.files.models as files_models
    import itou.geiq_assessments.models as geiq_assessments_models
    import itou.gps.models as gps_models
    import itou.institutions.models as institution_models
    import itou.invitations.models as invitation_models
    import itou.job_applications.models as job_applications_models
    import itou.jobs.models as jobs_models
    import itou.prescribers.models as prescribers_models
    import itou.siae_evaluations.models as siae_evaluations_models
    import itou.users.models as users_models
    import itou.utils.models as utils_models

    group_itou_admin_permissions = {
        account_models.EmailAddress: PERMS_ALL,
        analytics_models.Datum: PERMS_READ,
        approvals_models.Approval: PERMS_DELETE
        | PERMS_EDIT
        | PERMS_EXPORT_FT_API_REJECTIONS
        | PERMS_HANDLE_MANUAL_APPROVAL_REQUESTS,
        approvals_models.CancelledApproval: PERMS_READ,
        approvals_models.PoleEmploiApproval: PERMS_READ,
        approvals_models.Prolongation: PERMS_ALL,
        approvals_models.ProlongationRequest: PERMS_DELETE,
        approvals_models.Suspension: PERMS_ALL,
        asp_models.Commune: PERMS_READ,
        asp_models.Country: PERMS_READ,
        asp_models.Department: PERMS_READ,
        cities_models.City: PERMS_READ,
        communications_models.AnnouncementCampaign: PERMS_ALL,
        communications_models.AnnouncementItem: PERMS_ALL,
        companies_models.SiaeFinancialAnnex: PERMS_READ,
        companies_models.Company: PERMS_ALL,
        companies_models.SiaeConvention: PERMS_EDIT,
        companies_models.JobDescription: PERMS_DELETE,
        companies_models.CompanyMembership: PERMS_ADD,
        eligibility_models.AdministrativeCriteria: PERMS_READ,
        eligibility_models.EligibilityDiagnosis: PERMS_ALL,
        eligibility_models.GEIQAdministrativeCriteria: PERMS_READ,
        eligibility_models.GEIQEligibilityDiagnosis: PERMS_ALL,
        eligibility_models.GEIQSelectedAdministrativeCriteria: PERMS_ALL,
        eligibility_models.SelectedAdministrativeCriteria: PERMS_ALL,
        emails_models.Email: PERMS_READ,
        employee_record_models.EmployeeRecord: PERMS_EDIT | PERMS_DELETE,
        employee_record_models.EmployeeRecordUpdateNotification: PERMS_READ,
        employee_record_models.EmployeeRecordTransitionLog: PERMS_READ,
        external_data_models.ExternalDataImport: PERMS_DELETE,
        files_models.File: PERMS_READ,
        geiq_assessments_models.AssessmentCampaign: PERMS_ADD,
        geiq_assessments_models.Assessment: PERMS_READ,
        geiq_assessments_models.Employee: PERMS_READ,
        geiq_assessments_models.EmployeeContract: PERMS_READ,
        geiq_assessments_models.EmployeePrequalification: PERMS_READ,
        gps_models.FollowUpGroup: PERMS_DELETE,
        gps_models.FollowUpGroupMembership: PERMS_DELETE,
        institution_models.Institution: PERMS_ADD,
        institution_models.InstitutionMembership: PERMS_ADD,
        invitation_models.EmployerInvitation: PERMS_EDIT | PERMS_DELETE,
        invitation_models.LaborInspectorInvitation: PERMS_EDIT | PERMS_DELETE,
        invitation_models.PrescriberWithOrgInvitation: PERMS_EDIT | PERMS_DELETE,
        job_applications_models.JobApplication: PERMS_ALL | PERMS_EXPORT_JOB_APPLICATIONS_UNKNOWN_TO_FT,
        job_applications_models.JobApplicationTransitionLog: PERMS_READ,
        jobs_models.Appellation: PERMS_READ,
        jobs_models.Rome: PERMS_READ,
        prescribers_models.PrescriberMembership: PERMS_ADD,
        prescribers_models.PrescriberOrganization: PERMS_ALL,
        siae_evaluations_models.Calendar: PERMS_ADD,
        siae_evaluations_models.EvaluationCampaign: PERMS_READ,
        siae_evaluations_models.EvaluatedSiae: PERMS_READ,
        siae_evaluations_models.EvaluatedJobApplication: PERMS_READ,
        siae_evaluations_models.EvaluatedAdministrativeCriteria: PERMS_READ,
        siae_evaluations_models.Sanctions: PERMS_READ,
        users_models.User: PERMS_ALL | PERMS_HIJACK | PERMS_EXPORT_CTA | PERMS_MERGE_USERS,
        users_models.JobSeekerProfile: PERMS_EDIT | PERMS_DELETE,
        users_models.NirModificationRequest: PERMS_EDIT | PERMS_DELETE,
        utils_models.PkSupportRemark: PERMS_ADD,
        utils_models.UUIDSupportRemark: PERMS_ADD,
    }
    group_gps_admin_permissions = {
        companies_models.Company: PERMS_READ,
        gps_models.FollowUpGroup: PERMS_ALL,
        gps_models.FollowUpGroupMembership: PERMS_ALL,
        job_applications_models.JobApplication: PERMS_READ,
        job_applications_models.JobApplicationTransitionLog: PERMS_READ,
        prescribers_models.PrescriberOrganization: PERMS_READ,
        users_models.User: PERMS_ADD | PERMS_HIJACK | PERMS_EXPORT_CTA,
        users_models.JobSeekerProfile: PERMS_EDIT,
    }
    group_pilotage_admin_permissions = {
        analytics_models.StatsDashboardVisit: PERMS_READ,
        approvals_models.Approval: PERMS_READ,
        approvals_models.CancelledApproval: PERMS_READ,
        approvals_models.PoleEmploiApproval: PERMS_READ,
        approvals_models.Prolongation: PERMS_READ,
        approvals_models.Suspension: PERMS_READ,
        companies_models.Company: PERMS_READ,
        companies_models.CompanyMembership: PERMS_READ,
        institution_models.Institution: PERMS_ADD,
        institution_models.InstitutionMembership: PERMS_ADD,
        job_applications_models.JobApplication: PERMS_READ,
        job_applications_models.JobApplicationTransitionLog: PERMS_READ,
        prescribers_models.PrescriberOrganization: PERMS_READ,
        prescribers_models.PrescriberMembership: PERMS_READ,
        users_models.User: PERMS_HIJACK | PERMS_EXPORT_CTA,
    }

    return {
        "itou-admin": {**group_itou_admin_permissions},
        "itou-admin-readonly": {
            **{model: perms & PERMS_READONLY for model, perms in group_itou_admin_permissions.items()}
        },
        "gps-admin": {**group_gps_admin_permissions},
        "gps-admin-readonly": {
            **{model: perms & PERMS_READONLY for model, perms in group_gps_admin_permissions.items()}
        },
        "pilotage-admin": {**group_pilotage_admin_permissions},
        "pilotage-admin-readonly": {
            **{model: perms & PERMS_READONLY for model, perms in group_pilotage_admin_permissions.items()}
        },
        "rdvi": {
            companies_models.Company: PERMS_READ,
            companies_models.CompanyMembership: PERMS_READ,
            users_models.User: PERMS_READ,
        },
    }


def to_perm_codenames(model, perms_set):
    return [f"{perm}_{model._meta.model_name}" if perm in PERMS_ALL else perm for perm in perms_set]


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    help = "Synchronize groups and permissions."

    def handle(self, **options):
        for group, raw_permissions in sorted(get_permissions_dict().items()):
            all_codenames = [
                perm_code for model, perms in raw_permissions.items() for perm_code in to_perm_codenames(model, perms)
            ]
            perms = Permission.objects.filter(codename__in=all_codenames)
            group, created = Group.objects.get_or_create(name=group)
            group.permissions.clear()
            group.permissions.add(*perms)
            if created:
                self.logger.info(f"group name={group} created")
            else:
                self.logger.info(f"permissions of group={group} updated")
        self.logger.info("All done!")
