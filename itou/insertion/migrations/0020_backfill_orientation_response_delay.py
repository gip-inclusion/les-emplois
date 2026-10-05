import math

from django.db import migrations
from django.db.models import Avg, F, OuterRef, Subquery

from itou.insertion.enums import OrientationStatus, OrientationTransition


def forwards(apps, schema_editor):
    Orientation = apps.get_model("insertion", "Orientation")
    OrientationTransitionLog = apps.get_model("insertion", "OrientationTransitionLog")
    Service = apps.get_model("insertion", "Service")

    # Missing processing_date: backfill from the first accept/refuse transition log.
    log_timestamp = (
        OrientationTransitionLog.objects.filter(
            orientation_id=OuterRef("pk"),
            transition__in=[OrientationTransition.ACCEPT, OrientationTransition.REFUSE],
        )
        .order_by("timestamp")
        .values("timestamp")[:1]
    )
    Orientation.objects.filter(
        processing_date__isnull=True,
        status__in=[OrientationStatus.ACCEPTED, OrientationStatus.REFUSED],
    ).update(processing_date=Subquery(log_timestamp))

    # Average response delay in days per service (accepted/refused orientations with processing_date).
    service_delays = (
        Orientation.objects.filter(
            status__in=[OrientationStatus.ACCEPTED, OrientationStatus.REFUSED],
            processing_date__isnull=False,
        )
        .values("service_id")
        .annotate(avg_delay=Avg(F("processing_date") - F("created_at")))
        .values_list("service_id", "avg_delay")
    )

    # Drop imported DORA values; set average only for services with orientation history.
    Service.objects.all().update(average_orientation_response_delay_days=None)
    services_to_update = []
    for service_id, avg_delay in service_delays:
        services_to_update.append(
            Service(
                pk=service_id,
                average_orientation_response_delay_days=math.ceil(avg_delay.total_seconds() / (60 * 60 * 24)),
            )
        )
    Service.objects.bulk_update(
        services_to_update,
        ["average_orientation_response_delay_days"],
        batch_size=1000,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0019_service_and_structure_di_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
