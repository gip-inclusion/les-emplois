from django.db import transaction
from django.db.models import Min
from django.template import loader

from itou.job_applications.enums import RefusalReason
from itou.job_applications.models import JobApplication
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=40)

    def handle(self, limit, **options):
        job_applications_count = 0
        job_seekers_count = 0
        answer = loader.render_to_string("apply/refusal_messages/auto.txt")

        job_seekers_with_their_rejectable_applications = (
            JobApplication.objects.automatically_rejectable_applications()
            .values("job_seeker")
            .annotate(min_updated_at=Min("updated_at"))
            .order_by("min_updated_at")
        )[:limit]

        for job_seeker in job_seekers_with_their_rejectable_applications:
            with transaction.atomic():
                job_seeker_applications = (
                    JobApplication.objects.filter(job_seeker_id=job_seeker["job_seeker"])
                    .automatically_rejectable_applications()
                    .select_for_update()
                )

                for job_seeker_job_application in job_seeker_applications:
                    job_seeker_job_application.refusal_reason = RefusalReason.AUTO
                    job_seeker_job_application.refusal_reason_shared_with_job_seeker = True
                    job_seeker_job_application.answer = answer
                    job_seeker_job_application.refuse(user=None)
                    job_applications_count += 1
                job_seekers_count += 1

        self.logger.info(
            "%s auto rejected job applications for %s job seekers.",
            job_applications_count,
            job_seekers_count,
        )
