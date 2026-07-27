import datetime

from django.conf import settings
from django.db.models import Max
from itoutils.django.commands import dry_runnable

from itou.insertion.models import Orientation
from itou.utils.apis.dora import DoraAPIClient, DoraApiItemsIterator
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """Synchronise le statut des orientations émises par Les Emplois depuis DORA."""

    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        # Synchronisation incrémentale : on ne demande à DORA que les orientations dont le
        # statut a évolué depuis la dernière mise à jour appliquée localement. La borne DORA
        # est incluse ; re-traiter l'orientation limite est sans effet (mise à jour idempotente).
        watermark = Orientation.objects.aggregate(m=Max("dora_status_updated_at"))["m"]
        params = {"updated_after": watermark.isoformat()} if watermark else {}

        with DoraAPIClient(settings.DORA_API_BASE_URL, settings.DORA_API_TOKEN) as client:
            statuses = {}
            for item in DoraApiItemsIterator(client.orientation_statuses, params=params):
                processing_date = item["processing_date"]
                statuses[item["emplois_sync_uid"]] = (
                    item["status"],
                    datetime.datetime.fromisoformat(processing_date) if processing_date else None,
                    datetime.datetime.fromisoformat(item["updated_at"]),
                )

        self.logger.info("Retrieved count=%d orientation statuses from DORA", len(statuses))

        orientations = Orientation.objects.filter(id__in=statuses).only(
            "id", "status", "processing_date", "dora_status_updated_at"
        )
        to_update = []
        for orientation in orientations:
            status, processing_date, updated_at = statuses.pop(str(orientation.id))
            if (
                orientation.status == status
                and orientation.processing_date == processing_date
                and orientation.dora_status_updated_at == updated_at
            ):
                continue
            orientation.status = status
            orientation.processing_date = processing_date
            orientation.dora_status_updated_at = updated_at
            to_update.append(orientation)

        Orientation.objects.bulk_update(to_update, ["status", "processing_date", "dora_status_updated_at"])
        self.logger.info("Updated count=%d orientation statuses", len(to_update))

        if statuses:
            self.logger.warning(
                "Ignored count=%d unknown orientations: %s",
                len(statuses),
                ", ".join(sorted(statuses)),
            )
