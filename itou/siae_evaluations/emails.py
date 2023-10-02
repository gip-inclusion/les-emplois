import urllib.parse

from django.urls import reverse

from itou.utils import constants as global_constants
from itou.utils.emails import get_email_message
from itou.utils.urls import get_absolute_url


class CampaignEmailFactory:
    def __init__(self, evaluation_campaign):
        self.evaluation_campaign = evaluation_campaign
        self.recipients = evaluation_campaign.institution.active_members.values_list("email", flat=True)

    def ratio_to_select(self):
        context = {
            "dashboard_url": get_absolute_url(reverse("dashboard:index")),
        }
        subject = "siae_evaluations/email/to_institution_ratio_to_select_subject.txt"
        body = "siae_evaluations/email/to_institution_ratio_to_select_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def selected_siae(self):
        context = {
            "evaluated_period_start_at": self.evaluation_campaign.evaluated_period_start_at,
            "evaluated_period_end_at": self.evaluation_campaign.evaluated_period_end_at,
        }
        subject = "siae_evaluations/email/to_institution_selected_siae_subject.txt"
        body = "siae_evaluations/email/to_institution_selected_siae_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def transition_to_adversarial_stage(self, siaes_forced_to_adversarial_stage, siaes_accepted_by_default):
        context = {
            "siaes_forced_to_adversarial_stage": siaes_forced_to_adversarial_stage,
            "siaes_accepted_by_default": siaes_accepted_by_default,
        }
        subject = "siae_evaluations/email/to_institution_siaes_transition_to_adversarial_stage_subject.txt"
        body = "siae_evaluations/email/to_institution_siaes_transition_to_adversarial_stage_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def submission_frozen(self):
        subject = "siae_evaluations/email/to_institution_siaes_submission_frozen_subject.txt"
        body = "siae_evaluations/email/to_institution_siaes_submission_frozen_body.txt"
        return get_email_message(self.recipients, {}, subject, body)

    def submission_frozen_reminder(self):
        context = {"institution_name": self.evaluation_campaign.institution.name}
        subject = "siae_evaluations/email/to_institution_siaes_submission_frozen_reminder_subject.txt"
        body = "siae_evaluations/email/to_institution_siaes_submission_frozen_reminder_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def close(self):
        context = {
            "evaluated_siaes_list_url": get_absolute_url(
                reverse(
                    "siae_evaluations_views:institution_evaluated_siae_list",
                    kwargs={"evaluation_campaign_pk": self.evaluation_campaign.pk},
                )
            )
        }
        subject = "siae_evaluations/email/to_institution_campaign_close_subject.txt"
        body = "siae_evaluations/email/to_institution_campaign_close_body.txt"
        return get_email_message(self.recipients, context, subject, body)


class InstitutionEmailFactory:
    def __init__(self, evaluated_siae):
        self.evaluated_siae = evaluated_siae
        self.recipients = evaluated_siae.evaluation_campaign.institution.active_members.values_list("email", flat=True)

    def submitted_by_siae(self):
        context = {
            "siae": self.evaluated_siae.siae,
            "dashboard_url": get_absolute_url(reverse("dashboard:index")),
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
            "url": get_absolute_url(evaluated_siae_url),
        }
        subject = "siae_evaluations/email/to_siae_selected_subject.txt"
        body = "siae_evaluations/email/to_siae_selected_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def accepted(self, adversarial=False):
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "adversarial": adversarial,
        }
        subject = "siae_evaluations/email/to_siae_accepted_subject.txt"
        body = "siae_evaluations/email/to_siae_accepted_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def force_accepted(self):
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
        }
        subject = "siae_evaluations/email/to_siae_force_accepted_subject.txt"
        body = "siae_evaluations/email/to_siae_force_accepted_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def notify_before_adversarial_stage(self):
        job_app_list_url = reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        context = {
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "evaluated_job_app_list_url": get_absolute_url(job_app_list_url),
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
            "auto_prescription_url": get_absolute_url(auto_prescription_url),
            "siae_evaluation_handbook_url": urllib.parse.urljoin(
                global_constants.ITOU_HELP_CENTER_URL,
                "/sections/15257969468817-Contrôle-a-posteriori-pour-les-SIAE/",
            ),
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
            "adversarial_stage_start": self.evaluated_siae.evaluation_campaign.calendar.adversarial_stage_start,
            "evaluation_campaign": self.evaluated_siae.evaluation_campaign,
            "siae": self.evaluated_siae.siae,
            "evaluated_job_app_list_url": get_absolute_url(job_app_list_url),
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

    def not_sanctioned(self):
        context = {"sanctions": self.evaluated_siae.sanctions}
        subject = "siae_evaluations/email/to_siae_not_sanctioned_subject.txt"
        body = "siae_evaluations/email/to_siae_not_sanctioned_body.txt"
        return get_email_message(self.recipients, context, subject, body)

    def sanctioned(self):
        context = {"sanctions": self.evaluated_siae.sanctions}
        subject = "siae_evaluations/email/to_siae_sanctioned_subject.txt"
        body = "siae_evaluations/email/to_siae_sanctioned_body.txt"
        return get_email_message(self.recipients, context, subject, body)
