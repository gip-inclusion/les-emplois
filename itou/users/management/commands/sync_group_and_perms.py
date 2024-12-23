from django.contrib.auth.models import Group, Permission
from django.db import transaction

from itou.utils.command import BaseCommand


PERMS_ALL = {"add", "change", "delete", "view"}
PERMS_DELETE = {"change", "delete", "view"}
PERMS_ADD = {"add", "change", "view"}
PERMS_EDIT = {"change", "view"}
PERMS_READ = {"view"}


def get_permissions_dict():
    # lazy-import necessary models. Better than using string since we can then use introspection
    # and tooling will help us with refactoring, dead code and models, etc.
    import allauth.account.models as account_models

    import itou.analytics.models as analytics_models
    import itou.approvals.models as approvals_models
    import itou.asp.models as asp_models
    import itou.cities.models as cities_models
    import itou.companies.models as companies_models
    import itou.eligibility.models as eligibility_models
    import itou.employee_record.models as employee_record_models
    import itou.institutions.models as institution_models
    import itou.invitations.models as invitation_models
    import itou.job_applications.models as job_applications_models
    import itou.jobs.models as jobs_models
    import itou.prescribers.models as prescribers_models
    import itou.siae_evaluations.models as siae_evaluations_models
    import itou.users.models as users_models

    always_read_only_models = {
        analytics_models.Datum,
        analytics_models.StatsDashboardVisit,
        approvals_models.CancelledApproval,
        approvals_models.PoleEmploiApproval,
        asp_models.Commune,
        asp_models.Country,
        asp_models.Department,
        cities_models.City,
        eligibility_models.AdministrativeCriteria,
        job_applications_models.JobApplicationTransitionLog,
        jobs_models.Appellation,
        jobs_models.Rome,
        companies_models.SiaeFinancialAnnex,
        siae_evaluations_models.Calendar,
        siae_evaluations_models.EvaluationCampaign,
        siae_evaluations_models.EvaluatedSiae,
        siae_evaluations_models.EvaluatedJobApplication,
        siae_evaluations_models.EvaluatedAdministrativeCriteria,
        siae_evaluations_models.Sanctions,
    }
    group_itou_admin_permissions = {
        account_models.EmailAddress: PERMS_ADD,
        approvals_models.Approval: PERMS_ALL,
        approvals_models.Suspension: PERMS_ALL,
        approvals_models.Prolongation: PERMS_ALL,
        employee_record_models.EmployeeRecord: PERMS_DELETE,
        eligibility_models.EligibilityDiagnosis: PERMS_ADD,
        eligibility_models.SelectedAdministrativeCriteria: PERMS_ALL,
        institution_models.Institution: PERMS_ADD,
        institution_models.InstitutionMembership: PERMS_ALL,
        invitation_models.LaborInspectorInvitation: PERMS_DELETE,
        invitation_models.PrescriberWithOrgInvitation: PERMS_DELETE,
        invitation_models.EmployerInvitation: PERMS_DELETE,
        job_applications_models.JobApplication: PERMS_DELETE,
        prescribers_models.PrescriberMembership: PERMS_ALL,
        prescribers_models.PrescriberOrganization: PERMS_ADD,
        companies_models.Company: PERMS_ADD,
        companies_models.SiaeConvention: PERMS_EDIT,
        companies_models.JobDescription: PERMS_ALL,
        companies_models.CompanyMembership: PERMS_ALL,
        users_models.User: PERMS_ADD,
        users_models.JobSeekerProfile: PERMS_EDIT,
    }

    return {
        "itou-admin": {
            **group_itou_admin_permissions,
            **{model: PERMS_READ for model in always_read_only_models},
        },
        "itou-admin-readonly": {
            **{model: PERMS_READ for model in group_itou_admin_permissions},
            **{model: PERMS_READ for model in always_read_only_models},
        },
    }


def to_perm_codenames(model, perms_set):
    return [f"{perm}_{model._meta.model_name}" for perm in perms_set]


class Command(BaseCommand):
    help = "Synchronize groups and permissions."

    @transaction.atomic
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
                self.stdout.write(f"group name={group} created")
            else:
                self.stdout.write(f"permissions of group={group} updated")
        self.stdout.write("All done!")
