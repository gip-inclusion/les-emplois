from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Synchronize groups and permissions.

    To run the command:
        django-admin sync_group_and_perms
    """

    help = "Synchronize groups and permissions."

    def handle(self, **options):

        # This group contains the permissions assigned to the Itou team members.
        GROUP_NAME = "itou-admin"

        perms_codenames = [
            # account.EmailAddress
            "add_emailaddress",
            "change_emailaddress",
            "view_emailaddress",
            # approvals.Approval
            "add_approval",
            "change_approval",
            "delete_approval",
            "view_approval",
            # approvals.PoleEmploiApproval
            "view_poleemploiapproval",
            # approvals.Suspension
            "add_suspension",
            "change_suspension",
            "delete_suspension",
            "view_suspension",
            # cities.City
            "view_city",
            # eligibility.AdministrativeCriteria
            "view_administrativecriteria",
            # eligibility.EligibilityDiagnosis
            "add_eligibilitydiagnosis",
            "change_eligibilitydiagnosis",
            "view_eligibilitydiagnosis",
            # eligibility.SelectedAdministrativeCriteria
            "add_selectedadministrativecriteria",
            "change_selectedadministrativecriteria",
            "delete_selectedadministrativecriteria",
            "view_selectedadministrativecriteria",
            # invitations.PrescriberWithOrgInvitation
            "change_prescriberwithorginvitation",
            "delete_prescriberwithorginvitation",
            "view_prescriberwithorginvitation",
            # invitations.SiaeStaffInvitation
            "change_siaestaffinvitation",
            "delete_siaestaffinvitation",
            "view_siaestaffinvitation",
            # job_applications.JobApplication
            "view_jobapplication",
            "view_jobapplicationtransitionlog",
            # jobs.Appellation
            "view_appellation",
            # jobs.Rome
            "view_rome",
            # prescribers.PrescriberMembership
            "add_prescribermembership",
            "change_prescribermembership",
            "delete_prescribermembership",
            "view_prescribermembership",
            # prescribers.PrescriberOrganization
            "add_prescriberorganization",
            "change_prescriberorganization",
            "view_prescriberorganization",
            # siaes.Siae
            "add_siae",
            "change_siae",
            "view_siae",
            # siaes.SiaeConvention
            "change_siaeconvention",
            "view_siaeconvention",
            # siaes.SiaeFinancialAnnex
            "view_siaefinancialannex",
            # siaes.SiaeJobDescription
            "add_siaejobdescription",
            "change_siaejobdescription",
            "delete_siaejobdescription",
            "view_siaejobdescription",
            # siaes.SiaeMembership
            "add_siaemembership",
            "change_siaemembership",
            "delete_siaemembership",
            "view_siaemembership",
            # users.User
            "add_user",
            "change_user",
            "view_user",
            # ASP
            "view_commune",
            "view_country",
            "view_department",
            "view_educationlevel",
            "view_measure",
            "view_employertype",
        ]

        perms = Permission.objects.filter(codename__in=perms_codenames)

        group, created = Group.objects.get_or_create(name=GROUP_NAME)

        group.permissions.clear()
        group.permissions.add(*perms)

        if created:
            self.stdout.write(f"Group '{GROUP_NAME}' created.")
        self.stdout.write(f"Permissions of '{GROUP_NAME}' updated.")
        self.stdout.write("Done!")
