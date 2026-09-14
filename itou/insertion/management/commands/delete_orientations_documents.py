from dateutil.relativedelta import relativedelta
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.insertion.models import Orientation
from itou.utils.command import BaseCommand
from itou.utils.templatetags.str_filters import pluralizefr


class Command(BaseCommand):
    """
    Remove documents attached to orientations. At this point, only ACCEPTED orientations should still have
    documents, as we delete documents when expiring on refusing orientations.
    The filter is wider just in case.
    """

    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    @dry_runnable
    def handle(self, *, wet_run, limit, **options):
        now = timezone.now()
        old_orientations = Orientation.objects.filter(
            created_at__lte=now - relativedelta(months=Orientation.DOCUMENTS_EXPIRATION_MONTHS),
            documents__isnull=False,
        ).order_by("created_at", "pk")[:limit]

        for orientation in old_orientations:
            orientation.delete_documents()

        s = pluralizefr(len(old_orientations))
        self.logger.info(
            f"Found and deleted attached documents for {len(old_orientations)} orientation{s}.",
        )
