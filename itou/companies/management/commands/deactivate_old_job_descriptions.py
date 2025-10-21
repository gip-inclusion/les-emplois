import datetime

from django.db.models import Prefetch
from django.utils import timezone

from itou.companies.models import CompanyMembership, JobDescription
from itou.companies.notifications import OldJobDescriptionDeactivationNotification
from itou.utils.command import BaseCommand


DEACTIVATION_DELAY = datetime.timedelta(days=90)
BATCH_SIZE = 200  # Limit the number of sent notifications by limiting the number of deactivated job descriptions


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def handle(self, verbosity, **options):
        old_job_descriptions_qs = (
            JobDescription.objects.active()
            .is_internal()  # Exclude external sources such as FT API
            .exclude(last_employer_update_at__gte=timezone.now() - DEACTIVATION_DELAY)
        )
        old_job_descriptions = list(
            old_job_descriptions_qs.select_related("company", "appellation", "location")
            .prefetch_related(
                Prefetch("company__memberships", queryset=CompanyMembership.objects.select_related("user"))
            )
            .order_by("last_employer_update_at")[:BATCH_SIZE]
        )
        deactivated_nb = JobDescription.objects.filter(
            pk__in=[old_job_desc.pk for old_job_desc in old_job_descriptions]
        ).update(is_active=False)
        for old_job_description in old_job_descriptions:
            # Only send to active members (the default manager checks both the user and membership is_active statuses)
            for membership in old_job_description.company.memberships.all():
                OldJobDescriptionDeactivationNotification(
                    membership.user,
                    old_job_description.company,
                    job_description=old_job_description,
                ).send()
        self.logger.info(f"Deactivated {deactivated_nb} JobDescriptions")
        # More than one day delay
        if old_job_descriptions_qs.count() > BATCH_SIZE:
            self.logger.error("Too many old JobDescriptions to deactivate")
