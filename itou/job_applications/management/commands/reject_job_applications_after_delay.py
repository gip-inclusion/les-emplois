from django.core.management.base import CommandError
from django.template.defaultfilters import pluralize

from itou.job_applications.enums import RefusalReason
from itou.job_applications.models import JobApplication
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def get_answer_text_from_file(self):
        with open("itou/templates/apply/refusal_messages/auto.txt") as file:
            content = file.read()
        if not content:
            raise CommandError("Auto refusal message is empty.")
        return content

    def handle(self, **options):
        job_application_agg_array = JobApplication.objects.job_applications_rejectable_after_delay()
        job_application_ids = [str(uuid) for item in job_application_agg_array for uuid in item["applications"]]
        job_applications = JobApplication.objects.filter(id__in=job_application_ids)

        job_applications.select_for_update()

        answer = self.get_answer_text_from_file()

        for job_application in job_applications:
            job_application.refusal_reason = RefusalReason.AUTO
            job_application.refusal_reason_shared_with_job_seeker = True
            job_application.answer = answer

            job_application.refuse(user=None, disable_notif_to_proxy=True)

        s = pluralize(job_applications.count())
        self.logger.info(f"{job_applications.count()} auto rejected job application{s}.")
