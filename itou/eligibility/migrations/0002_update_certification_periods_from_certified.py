import logging
import time
from itertools import batched
from math import ceil

from django.db import migrations, transaction

from itou.utils.types import InclusiveDateRange


logger = logging.getLogger(__name__)


def forwards(apps, editor):
    SelectedAdministrativeCriteria = apps.get_model("eligibility", "SelectedAdministrativeCriteria")
    GEIQSelectedAdministrativeCriteria = apps.get_model("eligibility", "GEIQSelectedAdministrativeCriteria")
    BATCH_SIZE = 200

    print()
    for model in [SelectedAdministrativeCriteria, GEIQSelectedAdministrativeCriteria]:
        model.objects.filter(certified=False).update(certification_period=InclusiveDateRange(empty=True))
        criteria_to_update_pks = list(model.objects.filter(certified=True).values_list("pk", flat=True))
        batches = ceil(len(criteria_to_update_pks) / BATCH_SIZE)
        for i, batch_pks in enumerate(batched(criteria_to_update_pks, BATCH_SIZE), 1):
            logger.info("Updating up to %d %s (%d/%d).", BATCH_SIZE, model.__class__.__name__, i, batches)
            batch_criterias = []
            with transaction.atomic():
                for selected_criteria in model.objects.filter(pk__in=batch_pks).select_for_update(
                    of=["self"], no_key=True
                ):
                    selected_criteria.certification_period = InclusiveDateRange(
                        selected_criteria.certification_period.lower
                    )
                    batch_criterias.append(selected_criteria)
                model.objects.bulk_update(batch_criterias, ["certification_period"])
            time.sleep(0.5)


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ("eligibility", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, elidable=True),
    ]
