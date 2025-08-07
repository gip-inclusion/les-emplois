from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.companies.models import JobDescription
from itou.utils.command import BaseCommand


DEACTIVATION_DELAY = relativedelta(years=1)


class Command(BaseCommand):
    def handle(self, verbosity, **options):
        deactivated_nb = (
            JobDescription.objects.active()
            .is_internal()  # Exclude external sources such as FT API
            .exclude(last_employer_update_at__gte=timezone.now() - DEACTIVATION_DELAY)
            .update(is_active=False)
        )
        self.logger.info(f"Deactivated {deactivated_nb} JobDescriptions")
