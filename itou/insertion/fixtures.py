import datetime

from django.utils import timezone

from itou.insertion.models import Orientation
from itou.users.enums import ActionKind
from itou.users.models import JobSeekerAssignment


# Orientation id: (days since creation, days since last update, days since processing)
ORIENTATION_AGES_IN_DAYS = {
    "3f0b9c52-6d1e-4a7b-9c2e-8a41d5f07b13": (2, 2, None),
    "7a2e4d91-0c38-4f6b-b5a7-1e9d3c6f2a84": (10, 6, None),
    "b41c7e08-92d5-4e3a-8f16-5c0a7b2d9e61": (20, 15, 15),
    "c9d83a57-1f4b-4b20-a6e9-3d72f8015c4e": (25, 22, 22),
    "e1257b3c-8a60-4d9f-9b41-f6c3a2e87d05": (45, 15, None),
    "5d6f1a28-e347-4c85-b0d2-9a8e4c71f36b": (5, 5, None),
    "92c4e6b0-5b1d-4f7e-8c3a-0e6d9f24a157": (14, 9, 9),
    "4b8e2f61-7c05-4d3a-a9e2-6f1c8d304b72": (3, 1, None),
    "d2a7c93e-15f8-4b60-8e4d-9b3f0a61c5e8": (30, 27, 27),
    "6e19b4d0-a3c7-4f85-b2d1-3c8e7f0a9d46": (12, 8, 8),
    "f3c05d8a-9e21-4a7b-b64f-0d2e8c17a593": (50, 20, None),
}


def update_orientation_dates():
    """Make demo orientations dates relative to now.

    `updated_at` is an `auto_now` field, so JSON fixtures can't set it. Relative dates also prevent
    pending orientations from looking stale, or being expired, after each weekly demo reset.
    """
    now = timezone.now()

    def days_ago(days):
        return None if days is None else now - datetime.timedelta(days=days)

    for orientation_id, (created, updated, processed) in ORIENTATION_AGES_IN_DAYS.items():
        # A queryset update() bypasses auto_now
        Orientation.objects.filter(pk=orientation_id).update(
            created_at=days_ago(created),
            updated_at=days_ago(updated),
            processing_date=days_ago(processed),
        )

    for assignment in JobSeekerAssignment.objects.filter(last_action_kind=ActionKind.ORIENT):
        last_orientation = (
            Orientation.objects.filter(
                beneficiary_id=assignment.job_seeker_id,
                sender_id=assignment.professional_id,
                sender_prescriber_organization_id=assignment.prescriber_organization_id,
                sender_company_id=assignment.company_id,
            )
            .order_by("-created_at")
            .first()
        )
        if last_orientation:
            JobSeekerAssignment.objects.filter(pk=assignment.pk).update(
                last_action_at=last_orientation.created_at,
                updated_at=last_orientation.created_at,
            )
