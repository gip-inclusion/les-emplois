from django.utils import timezone

from itou.jobs.models import Appellation, Rome
from itou.utils.apis import pe_api_enums, pole_emploi_api_client
from itou.utils.command import BaseCommand
from itou.utils.sync import yield_sync_diff


# more than the number of Romes (~500) but less than the number of Appellations (~11000)
BULK_CREATE_BATCH_SIZE = 1000


def pe_data_to_appellation(data, at):
    rome = Rome.objects.get(code=data["metier"]["code"])
    return Appellation(code=data["code"], name=data["libelle"], updated_at=at, rome_id=rome.pk)


def pe_data_to_rome(data, at):
    return Rome(code=data["code"], name=data["libelle"], updated_at=at)


class Command(BaseCommand):
    """As explained at the time of writing this command, we simple update or create the new entries here,
    still updating an `updated_at` column to at least keep track of the latest modification time.

    No ROMEs or Appellation has ever been removed in the last 3 years, so we consider this case as rare
    enough to not setup the whole process of keeping track of outdated objects in the sync, etc.
    """

    help = "Synchronizes ROMEs and Appellations from the PE API"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, *, wet_run, **options):
        now = timezone.now()
        pe_client = pole_emploi_api_client()

        romes_data = pe_client.referentiel(pe_api_enums.REFERENTIEL_ROME)
        for item in yield_sync_diff(romes_data, "code", Rome.objects.all(), "code", [("libelle", "name")]):
            self.stdout.write(item.label)

        if wet_run:
            romes = [pe_data_to_rome(item, now) for item in romes_data]
            Rome.objects.bulk_create(
                romes,
                batch_size=BULK_CREATE_BATCH_SIZE,
                update_conflicts=True,
                update_fields=("name", "updated_at"),
                unique_fields=("code",),
            )
            self.stdout.write(f"len={len(romes)} ROME entries have been created or updated.")

        appellations_data = pe_client.appellations()
        for item in yield_sync_diff(
            appellations_data, "code", Appellation.objects.all(), "code", [("libelle", "name")]
        ):
            self.stdout.write(item.label)

        if wet_run:
            appellations = [pe_data_to_appellation(item, now) for item in appellations_data]
            Appellation.objects.bulk_create(
                appellations,
                batch_size=BULK_CREATE_BATCH_SIZE,
                update_conflicts=True,
                update_fields=("name", "updated_at", "rome_id"),
                unique_fields=("code",),
            )
            self.stdout.write(f"len={len(appellations)} Appellation entries have been created or updated.")
