import datetime

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from itou.insertion.enums import OrientationStatus, OrientationTransition
from itou.insertion.models import Orientation, OrientationTransitionLog
from itou.job_applications.enums import SenderKind
from tests.insertion.factories import StructureFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory


@pytest.mark.django_db(transaction=True)
def test_backfill_orientation_response_delay_migration():
    call_command("migrate", "insertion", "0019", verbosity=0)
    try:
        historical_service = (
            MigrationExecutor(connection)
            .loader.project_state(("insertion", "0019_service_and_structure_di_fields"))
            .apps.get_model("insertion", "Service")
        )
        structure = StructureFactory()
        service = historical_service.objects.create(
            uid="service-with-delay",
            source_id=structure.source_id,
            structure_id=structure.pk,
            name="Service",
            description="Description",
            updated_on=datetime.date(2025, 1, 1),
            average_orientation_response_delay_days=16,
        )
        empty_service = historical_service.objects.create(
            uid="service-without-history",
            source_id=structure.source_id,
            structure_id=structure.pk,
            name="Service vide",
            description="Description",
            updated_on=datetime.date(2025, 1, 1),
            average_orientation_response_delay_days=80,
        )
        now = timezone.now()
        created_at = now - datetime.timedelta(days=4)
        accepted_at = now - datetime.timedelta(days=1)
        orientation = Orientation.objects.create(
            beneficiary=JobSeekerFactory(),
            sender=PrescriberFactory(membership=False),
            sender_kind=SenderKind.PRESCRIBER,
            sender_prescriber_organization=PrescriberOrganizationFactory(),
            service_id=service.pk,
            referent_first_name="Ada",
            referent_last_name="Lovelace",
            referent_email="ada@example.com",
            status=OrientationStatus.ACCEPTED,
            processing_date=None,
            created_at=created_at,
        )
        OrientationTransitionLog.objects.create(
            orientation=orientation,
            transition=OrientationTransition.ACCEPT,
            from_state=OrientationStatus.PENDING,
            to_state=OrientationStatus.ACCEPTED,
            timestamp=accepted_at,
        )

        call_command("migrate", "insertion", "0020", verbosity=0)

        orientation.refresh_from_db()
        service.refresh_from_db()
        empty_service.refresh_from_db()
        assert orientation.processing_date == accepted_at
        assert service.average_orientation_response_delay_days == 3
        assert empty_service.average_orientation_response_delay_days is None
    finally:
        call_command("migrate", verbosity=0)
