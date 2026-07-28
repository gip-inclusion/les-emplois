import datetime
from typing import NamedTuple

from django.conf import settings
from django.db.models import Max
from itoutils.django.commands import dry_runnable

from itou.insertion.models import Orientation
from itou.utils.apis.dora import DoraAPIClient, DoraApiItemsIterator
from itou.utils.command import BaseCommand


class DoraStatus(NamedTuple):
    status: str
    processing_date: datetime.datetime | None  # date à laquelle l'orientation a été traitée côté Dora
    dora_status_updated_at: datetime.datetime  # date de dernière modification côté DORA, borne de la synchro

    @classmethod
    def from_api_item(cls, item):
        processing_date = item["processing_date"]
        return cls(
            status=item["status"],
            processing_date=datetime.datetime.fromisoformat(processing_date) if processing_date else None,
            dora_status_updated_at=datetime.datetime.fromisoformat(item["updated_at"]),
        )

    @classmethod
    def from_orientation(cls, orientation):
        return cls(
            status=orientation.status,
            processing_date=orientation.processing_date,
            dora_status_updated_at=orientation.dora_status_updated_at,
        )


class Command(BaseCommand):
    """Synchronise le statut des orientations émises par Les Emplois depuis DORA."""

    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        # Incremental sync: we only ask DORA for the orientations whose status changed since the
        # last update applied locally. The bound is inclusive on DORA's side; processing the
        # boundary orientation again is harmless since the update is idempotent.
        watermark = Orientation.objects.aggregate(m=Max("dora_status_updated_at"))["m"]
        params = {"updated_after": watermark.isoformat()} if watermark else {}

        with DoraAPIClient(settings.DORA_API_BASE_URL, settings.DORA_API_TOKEN) as client:
            statuses = {
                item["emplois_sync_uid"]: DoraStatus.from_api_item(item)
                for item in DoraApiItemsIterator(client.orientation_statuses, params=params)
            }

        self.logger.info("Retrieved count=%d orientation statuses from DORA", len(statuses))

        orientations = list(Orientation.objects.filter(id__in=statuses).only("id", *DoraStatus._fields))
        # Dora only knows the orientations we sent it: an unknown uid means both databases
        # diverged, which has to be dealt with before syncing anything.
        if unknown := statuses.keys() - {str(orientation.id) for orientation in orientations}:
            raise RuntimeError(f"Unknown orientations from DORA: {', '.join(sorted(unknown))}")

        to_update = []
        for orientation in orientations:
            dora_status = statuses[str(orientation.id)]
            if dora_status == DoraStatus.from_orientation(orientation):
                continue
            orientation.status = dora_status.status
            orientation.processing_date = dora_status.processing_date
            orientation.dora_status_updated_at = dora_status.dora_status_updated_at
            to_update.append(orientation)

        Orientation.objects.bulk_update(to_update, DoraStatus._fields)
        self.logger.info("Updated count=%d orientation statuses", len(to_update))
