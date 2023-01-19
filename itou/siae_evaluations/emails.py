from django.conf import settings
from django.urls import reverse

from itou.utils import constants as global_constants
from itou.utils.emails import get_email_message


class CampaignEmailFactory:
    def __init__(self, evaluation_campaign):
        self.evaluation_campaign = evaluation_campaign
        self.recipients = evaluation_campaign.institution.active_members.values_list("email", flat=True)

    def ratio_to_select(self, ratio_selection_end_at):
        context = {
            "ratio_selection_end_at": ratio_selection_end_at,
            "dashboard_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{reverse('dashboard:index')}",
        }
        subject = "siae_evaluations/email/to_institution_ratio_to_select_subject.txt"
        body = "siae_evaluations/email/to_institution_ratio_to_select_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def selected_siae(self):
        context = {
            "end_date": self.evaluation_campaign.adversarial_stage_start_date,
            "evaluated_period_start_at": self.evaluation_campaign.evaluated_period_start_at,
            "evaluated_period_end_at": self.evaluation_campaign.evaluated_period_end_at,
        }
        subject = "siae_evaluations/email/to_institution_selected_siae_subject.txt"
        body = "siae_evaluations/email/to_institution_selected_siae_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def forced_to_adversarial_stage(self, evaluated_siaes):
        context = {"evaluated_siaes": evaluated_siaes}
        subject = "siae_evaluations/email/to_institution_siaes_forced_to_adversarial_stage_subject.txt"
        body = "siae_evaluations/email/to_institution_siaes_forced_to_adversarial_stage_body.txt"
        return get_email_message(self.recipients, context, subject, body)


class InstitutionEmailFactory:
    def __init__(self, evaluated_siae):
        self.evaluated_siae = evaluated_siae
        self.recipients = evaluated_siae.evaluation_campaign.institution.active_members.values_list("email", flat=True)

    def submitted_by_siae(self):
        context = {
            "siae": self.evaluated_siae.siae,
            "dashboard_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{reverse('dashboard:index')}",
        }
        subject = "siae_evaluations/email/to_institution_submitted_by_siae_subject.txt"
        body = "siae_evaluations/email/to_institution_submitted_by_siae_body.txt"
        return get_email_message(self.recipients, context, subject, body)


class SIAEEmailFactory:
    def __init__(self, evaluated_siae):
        self.evaluated_siae = evaluated_siae
        self.recipients = evaluated_siae.siae.active_admin_members.values_list("email", flat=True)

    def selected(self):
        evaluated_siae_url = reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        context = {
            "campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "end_date": self.evaluated_siae.evaluation_campaign.adversarial_stage_start_date,
            "url": (f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}" + evaluated_siae_url),
        }
        subject = "siae_evaluations/email/to_siae_selected_subject.txt"
        body = "siae_evaluations/email/to_siae_selected_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def reviewed(self, adversarial=False):
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "adversarial": adversarial,
        }
        subject = "siae_evaluations/email/to_siae_reviewed_subject.txt"
        body = "siae_evaluations/email/to_siae_reviewed_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def notify_before_adversarial_stage(self):
        job_app_list_url = reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "evaluated_job_app_list_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{job_app_list_url}",
            "itou_community_url": global_constants.ITOU_COMMUNITY_URL,
        }
        subject = "siae_evaluations/email/to_siae_notify_before_adversarial_stage_subject.txt"
        body = "siae_evaluations/email/to_siae_notify_before_adversarial_stage_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def adversarial_stage(self):
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
        }
        subject = "siae_evaluations/email/to_siae_adversarial_stage_subject.txt"
        body = "siae_evaluations/email/to_siae_adversarial_stage_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def forced_to_adversarial_stage(self):
        auto_prescription_url = reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "auto_prescription_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{auto_prescription_url}",
        }
        subject = "siae_evaluations/email/to_siae_forced_to_adversarial_stage_subject.txt"
        body = "siae_evaluations/email/to_siae_forced_to_adversarial_stage_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def notify_before_campaign_close(self):
        job_app_list_url = reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        context = {
            "adversarial_stage_start": self.evaluated_siae.evaluation_campaign.adversarial_stage_start_date,
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "evaluated_job_app_list_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{job_app_list_url}",
            "itou_community_url": global_constants.ITOU_COMMUNITY_URL,
        }
        subject = "siae_evaluations/email/to_siae_notify_before_campaign_close_subject.txt"
        body = "siae_evaluations/email/to_siae_notify_before_campaign_close_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def refused(self):
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
        }
        subject = "siae_evaluations/email/to_siae_refused_subject.txt"
        body = "siae_evaluations/email/to_siae_refused_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def refused_no_proofs(self):
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
        }
        subject = "siae_evaluations/email/to_siae_refused_no_proofs_subject.txt"
        body = "siae_evaluations/email/to_siae_refused_no_proofs_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def sanctioned(self):
        dashboard_url = reverse("dashboard:index")
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "dashboard_url": (f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}" + dashboard_url),
        }
        subject = "siae_evaluations/email/to_siae_sanctioned_subject.txt"
        body = "siae_evaluations/email/to_siae_sanctioned_body.txt"
        return get_email_message(self.recipients, context, subject, body)
