from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction


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
    import itou.companies.models as siaes_models
    import itou.eligibility.models as eligibility_models
    import itou.employee_record.models as employee_record_models
    import itou.institutions.models as institution_models
    import itou.invitations.models as invitation_models
    import itou.job_applications.models as job_applications_models
    import itou.jobs.models as jobs_models
    import itou.prescribers.models as prescribers_models
    import itou.siae_evaluations.models as siae_evaluations_models
    import itou.users.models as users_models

    return {
        "itou-admin": {
            account_models.EmailAddress: PERMS_ADD,
            analytics_models.Datum: PERMS_READ,
            analytics_models.StatsDashboardVisit: PERMS_READ,
            approvals_models.Approval: PERMS_ALL,
            approvals_models.CancelledApproval: PERMS_READ,
            approvals_models.PoleEmploiApproval: PERMS_READ,
            approvals_models.Suspension: PERMS_ALL,
            approvals_models.Prolongation: PERMS_ALL,
            asp_models.Commune: PERMS_READ,
            asp_models.Country: PERMS_READ,
            asp_models.Department: PERMS_READ,
            cities_models.City: PERMS_READ,
            employee_record_models.EmployeeRecord: PERMS_DELETE,
            eligibility_models.AdministrativeCriteria: PERMS_READ,
            eligibility_models.EligibilityDiagnosis: PERMS_ADD,
            eligibility_models.SelectedAdministrativeCriteria: PERMS_ALL,
            institution_models.Institution: PERMS_ADD,
            institution_models.InstitutionMembership: PERMS_ALL,
            invitation_models.LaborInspectorInvitation: PERMS_DELETE,
            invitation_models.PrescriberWithOrgInvitation: PERMS_DELETE,
            invitation_models.EmployerInvitation: PERMS_DELETE,
            job_applications_models.JobApplication: PERMS_DELETE,
            job_applications_models.JobApplicationTransitionLog: PERMS_READ,
            jobs_models.Appellation: PERMS_READ,
            jobs_models.Rome: PERMS_READ,
            prescribers_models.PrescriberMembership: PERMS_ALL,
            prescribers_models.PrescriberOrganization: PERMS_ADD,
            siaes_models.Siae: PERMS_ADD,
            siaes_models.SiaeConvention: PERMS_EDIT,
            siaes_models.SiaeFinancialAnnex: PERMS_READ,
            siaes_models.SiaeJobDescription: PERMS_ALL,
            siaes_models.SiaeMembership: PERMS_ALL,
            siae_evaluations_models.Calendar: PERMS_READ,
            siae_evaluations_models.EvaluationCampaign: PERMS_READ,
            siae_evaluations_models.EvaluatedSiae: PERMS_READ,
            siae_evaluations_models.EvaluatedJobApplication: PERMS_READ,
            siae_evaluations_models.EvaluatedAdministrativeCriteria: PERMS_READ,
            siae_evaluations_models.Sanctions: PERMS_READ,
            users_models.User: PERMS_ADD,
            users_models.JobSeekerProfile: PERMS_EDIT,
        },
        "itou-support-externe": {
            model: PERMS_READ
            for model in (
                account_models.EmailAddress,
                approvals_models.Approval,
                approvals_models.CancelledApproval,
                approvals_models.PoleEmploiApproval,
                approvals_models.Suspension,
                approvals_models.Prolongation,
                asp_models.Commune,
                asp_models.Country,
                asp_models.Department,
                cities_models.City,
                employee_record_models.EmployeeRecord,
                eligibility_models.AdministrativeCriteria,
                eligibility_models.EligibilityDiagnosis,
                eligibility_models.SelectedAdministrativeCriteria,
                institution_models.Institution,
                institution_models.InstitutionMembership,
                invitation_models.LaborInspectorInvitation,
                invitation_models.PrescriberWithOrgInvitation,
                invitation_models.EmployerInvitation,
                job_applications_models.JobApplication,
                job_applications_models.JobApplicationTransitionLog,
                jobs_models.Appellation,
                jobs_models.Rome,
                prescribers_models.PrescriberMembership,
                prescribers_models.PrescriberOrganization,
                siaes_models.Siae,
                siaes_models.SiaeConvention,
                siaes_models.SiaeFinancialAnnex,
                siaes_models.SiaeJobDescription,
                siaes_models.SiaeMembership,
                users_models.User,
                users_models.JobSeekerProfile,
            )
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
