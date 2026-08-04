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
    processing_date: datetime.datetime | None  # the date on which the orientation was processed by DORA
    dora_status_updated_at: datetime.datetime  # the date of the last modification on DORA side, synchronization point
    updated_at: datetime.datetime  # the date actually displayed in the interfaces

    @classmethod
    def from_api_item(cls, item):
        processing_date = item["processing_date"]
        dora_status_updated_at = datetime.datetime.fromisoformat(item["updated_at"])
        return cls(
            status=item["status"],
            processing_date=datetime.datetime.fromisoformat(processing_date) if processing_date else None,
            dora_status_updated_at=dora_status_updated_at,
            updated_at=dora_status_updated_at,
        )

    @classmethod
    def from_orientation(cls, orientation):
        return cls(
            status=orientation.status,
            processing_date=orientation.processing_date,
            dora_status_updated_at=orientation.dora_status_updated_at,
            updated_at=orientation.updated_at,
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
        # DORA only knows the orientations we sent it: an unknown uid means both databases
        # diverged, which has to be dealt with before syncing anything.
        if unknown := statuses.keys() - {str(orientation.id) for orientation in orientations}:
            raise RuntimeError(f"Unknown orientations from DORA: {', '.join(sorted(unknown))}")

        to_update = []
        for orientation in orientations:
            dora_status = statuses[str(orientation.id)]
            emplois_status = DoraStatus.from_orientation(orientation)
            if dora_status == emplois_status:
                continue
            elif emplois_status.updated_at > dora_status.updated_at:
                # This situation should not happen, we want to have only one source of truth.
                # For now it is DORA from which we update the status, processing_date and updated_at.
                # Later on, the orientations will be managed on Les Emplois and we don’t want to
                # overwrite the data -- we’ll have to figure out data reconciliation.
                self.logger.error("Trying to update orientation=%s with older DORA data", orientation.pk)
                continue
            orientation.status = dora_status.status
            orientation.processing_date = dora_status.processing_date
            orientation.dora_status_updated_at = dora_status.dora_status_updated_at
            orientation.updated_at = dora_status.updated_at
            to_update.append(orientation)

        Orientation.objects.bulk_update(to_update, DoraStatus._fields)
        self.logger.info("Updated count=%d orientation statuses", len(to_update))
