from django.urls import reverse
from django.utils import timezone

from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification
from itou.communications.dispatch.utils import ProfessionalNotification
from itou.companies.enums import CompanyKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.urls import get_absolute_url, get_tally_form_url


class EndOfJourneyNotificationMixin:
    """Provide what the footer of the end of journey emails needs, children define `feedback_mail`"""

    category = NotificationCategory.END_OF_JOURNEY

    def get_context(self):
        context = super().get_context()
        context["feedback_form_url"] = get_tally_form_url("kdDjod", mail=self.feedback_mail, role=self.feedback_role)
        context["notification_settings_url"] = get_absolute_url(reverse("dashboard:edit_user_notifications"))
        return context


class SiaeEndOfJourneyNotificationMixin(EndOfJourneyNotificationMixin):
    feedback_role = "siae"

    def is_applicable(self):
        return self.structure and self.structure.kind in CompanyKind.siae_kinds()


class PrescriberEndOfJourneyNotificationMixin(EndOfJourneyNotificationMixin):
    feedback_role = "prescripteur"

    def is_applicable(self):
        return isinstance(self.structure, PrescriberOrganization) and self.structure.is_authorized


@notifications_registry.register
class EndOfContractMonthlyRecapForEmployerNotification(
    SiaeEndOfJourneyNotificationMixin, ProfessionalNotification, EmailNotification
):
    """Notification sent each month to the SIAE contact of the employees whose contract ends"""

    MAX_CONTRACTS = 10

    name = "Récapitulatif mensuel des fins de contrat"
    subject_template = "companies/email/end_of_contract_monthly_recap_subject.txt"
    body_template = "companies/email/end_of_contract_monthly_recap_body.md"
    feedback_mail = 1

    @staticmethod
    def get_contract_line(contract):
        job_seeker_kwargs = {"public_id": contract.job_seeker.public_id}
        return {
            "contract": contract,
            "job_seeker_url": get_absolute_url(reverse("job_seekers_views:details", kwargs=job_seeker_kwargs)),
            "pro_support_report_url": get_absolute_url(
                reverse("job_seekers_views:create_pro_support_report", kwargs=job_seeker_kwargs)
            ),
        }

    def get_context(self):
        context = super().get_context()
        first_day_of_month = timezone.localdate().replace(day=1)
        last_month_contracts = [
            contract for contract in context["contracts"] if contract.end_date < first_day_of_month
        ]
        this_month_contracts = [
            contract for contract in context["contracts"] if contract.end_date >= first_day_of_month
        ]
        # Last month comes first, a group shorter than half of the list leaves its places to the other.
        last_month_contracts_shown = min(
            len(last_month_contracts), max(self.MAX_CONTRACTS // 2, self.MAX_CONTRACTS - len(this_month_contracts))
        )
        return context | {
            "last_month_contract_lines": [
                self.get_contract_line(contract) for contract in last_month_contracts[:last_month_contracts_shown]
            ],
            "last_month_contracts_count": len(last_month_contracts),
            "this_month_contract_lines": [
                self.get_contract_line(contract)
                for contract in this_month_contracts[: self.MAX_CONTRACTS - last_month_contracts_shown]
            ],
            "this_month_contracts_count": len(this_month_contracts),
            "end_of_journey_list_url": get_absolute_url(
                reverse("job_seekers_views:list_organization", query={"end_of_journey": "on"})
            ),
        }


@notifications_registry.register
class OldJobDescriptionDeactivationNotification(EmailNotification, ProfessionalNotification):
    """Notification sent to the members of a company when an old job description is deactivated"""

    name = "Désactivation de fiche de poste"
    category = NotificationCategory.JOB_DESCRIPTION
    subject_template = "companies/email/old_job_description_deactivated_subject.txt"
    body_template = "companies/email/old_job_description_deactivated_body.md"


@notifications_registry.register
class SpontaneousJobApplicationsDeactivationNotification(EmailNotification, ProfessionalNotification):
    """Notification sent to the members of a company when spontaneous applications are deactivated"""

    name = "Désactivation des candidatures spontanées"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "companies/email/spontaneous_jobapps_deactivated_subject.txt"
    body_template = "companies/email/spontaneous_jobapps_deactivated_body.md"
