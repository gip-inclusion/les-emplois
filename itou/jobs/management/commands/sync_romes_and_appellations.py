from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.jobs.models import Appellation, Rome
from itou.utils.apis import pe_api_enums
from itou.utils.apis.pole_emploi import pole_emploi_partenaire_api_client
from itou.utils.command import BaseCommand
from itou.utils.diff import CollectionDiffer, DiffItemKind


# more than the number of Romes (~500) but less than the number of Appellations (~11000)
BULK_CREATE_BATCH_SIZE = 1000


class Command(BaseCommand):
    """As explained at the time of writing this command, we simple update or create the new entries here,
    still updating an `updated_at` column to at least keep track of the latest modification time.

    No ROMEs or Appellation has ever been removed in the last 3 years, so we consider this case as rare
    enough to not setup the whole process of keeping track of outdated objects in the sync, etc.
    """

    ATOMIC_HANDLE = True

    help = "Synchronizes ROMEs and Appellations from the PE API"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        now = timezone.now()

        with pole_emploi_partenaire_api_client() as client:
            romes_data = client.referentiel(pe_api_enums.REFERENTIEL_ROME)
            appellations_data = client.appellations()

        # ROMEs
        to_create, to_update = [], []
        differ = CollectionDiffer(Rome.objects.all(), romes_data, "code", watched_data={"name": "libelle"})
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is DiffItemKind.ADDED:
                to_create.append(
                    Rome(
                        code=diff_item.key[0],
                        name=diff_item.data["name"].after,
                        updated_at=now,
                    )
                )
            if diff_item.kind is DiffItemKind.UPDATED:
                for current_item_attr, data_diff in diff_item.data.items():
                    setattr(diff_item.current_item, current_item_attr, data_diff.after)
                diff_item.current_item.updated_at = now
                to_update.append(diff_item.current_item)

        self.logger.info(differ.summary_label())

        created = Rome.objects.bulk_create(to_create, batch_size=BULK_CREATE_BATCH_SIZE)
        self.logger.info("count=%d ROME entries have been created.", len(created))
        updated = Rome.objects.bulk_update(to_update, {"name", "updated_at"}, batch_size=BULK_CREATE_BATCH_SIZE)
        self.logger.info("count=%d ROME entries have been updated.", updated)

        # Appellations
        rome_by_code = Rome.objects.in_bulk(field_name="code")
        to_create, to_update = [], []
        differ = CollectionDiffer(
            Appellation.objects.all(),
            appellations_data,
            "code",
            watched_data={"name": "libelle", "rome": "metier"},
            comparative_data_converters={"metier": lambda value: rome_by_code[value["code"]]},
        )
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is DiffItemKind.ADDED:
                to_create.append(
                    Appellation(
                        code=diff_item.key[0],
                        name=diff_item.data["name"].after,
                        rome=diff_item.data["rome"].after,
                        updated_at=now,
                    )
                )
            if diff_item.kind is DiffItemKind.UPDATED:
                for current_item_attr, data_diff in diff_item.data.items():
                    setattr(diff_item.current_item, current_item_attr, data_diff.after)
                diff_item.current_item.updated_at = now
                to_update.append(diff_item.current_item)

        self.logger.info(differ.summary_label())

        created = Appellation.objects.bulk_create(to_create, batch_size=BULK_CREATE_BATCH_SIZE)
        self.logger.info("count=%d Appellation entries have been created.", len(created))
        updated = Appellation.objects.bulk_update(
            to_update, {"name", "rome", "updated_at"}, batch_size=BULK_CREATE_BATCH_SIZE
        )
        self.logger.info("count=%d Appellation entries have been updated.", updated)
