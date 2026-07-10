from django.conf import settings
from django.db.models import Prefetch, Q
from django.utils import timezone

from itou.companies.models import Company, CompanyMembership
from itou.companies.notifications import SpontaneousJobApplicationsDeactivationNotification
from itou.utils.command import BaseCommand


BATCH_SIZE = 200


class Command(BaseCommand):
    """
    Deactivates spontaneous job applications for companies that haven't updated this method of recruitment in 90 days.
    """

    ATOMIC_HANDLE = True

    def handle(self, verbosity, **options):
        companies_without_update_qs = Company.objects.exclude(
            Q(spontaneous_applications_open_since__gte=timezone.now() - settings.DEACTIVATION_DELAY)
            | Q(spontaneous_applications_open_since__isnull=True)
        ).order_by("spontaneous_applications_open_since")
        companies_without_update = list(
            companies_without_update_qs.prefetch_related(
                Prefetch("memberships", queryset=CompanyMembership.objects.select_related("user"))
            )[:BATCH_SIZE]
        )
        deactivated_companies_nb = Company.objects.filter(
            pk__in=[company.pk for company in companies_without_update]
        ).update(spontaneous_applications_open_since=None)
        for company in companies_without_update:
            # Only send to active members (the default manager checks both the user and membership is_active statuses)
            for membership in company.memberships.all():
                SpontaneousJobApplicationsDeactivationNotification(membership.user, company).send()
        self.logger.info(f"Deactivated spontaneous job applications for {deactivated_companies_nb} Companies")
        if (count := companies_without_update_qs.count()) > BATCH_SIZE:
            self.logger.error(f"Too many Companies to deactivate spontaneous job applications for: {count}")
