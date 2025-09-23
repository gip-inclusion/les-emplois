from django.conf import settings
from django.db import transaction
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.approvals.models import CancelledApproval
from itou.archive.constants import EXPIRATION_PERIOD
from itou.archive.models import AnonymizedCancelledApproval
from itou.utils.command import BaseCommand, dry_runnable


def anonymized_cancelled_approval(obj):
    return AnonymizedCancelledApproval(
        had_pole_emploi_id=bool(obj.user_id_national_pe),
        had_nir=bool(obj.user_nir),
        nir_sex=obj.user_nir[0] if obj.user_nir else None,
        nir_year=obj.user_nir[1:3] if obj.user_nir else None,
        birth_year=obj.user_birthdate.year if obj.user_birthdate else None,
        origin_company_kind=obj.origin_siae_kind,
        origin_sender_kind=obj.origin_sender_kind,
        origin_prescriber_organization_kind=obj.origin_prescriber_organization_kind,
    )


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the anonymization of cancelled approvals",
        )

    @monitor(
        monitor_slug="anonymize_cancelled_approvals",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 6 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    @dry_runnable
    @transaction.atomic
    def handle(self, *args, wet_run, **options):
        if settings.SUSPEND_ANONYMIZE_CANCELLED_APPROVALS:
            self.logger.info("Anonymizing cancelled approvals is suspended, exiting command")
            return

        self.wet_run = wet_run

        expired_since = timezone.now() - EXPIRATION_PERIOD
        self.logger.info("Anonymizing cancelled approvals after expiration period, expired since: %s", expired_since)

        cancelled_approval_to_anonymize = list(
            CancelledApproval.objects.filter(end_at__lte=expired_since)
            .order_by("end_at", "id")
            .select_for_update(of=["self"], skip_locked=True)
        )
        archived_cancelled_approval = [anonymized_cancelled_approval(obj) for obj in cancelled_approval_to_anonymize]

        AnonymizedCancelledApproval.objects.bulk_create(archived_cancelled_approval)
        CancelledApproval.objects.filter(id__in=[obj.id for obj in cancelled_approval_to_anonymize]).delete()

        self.logger.info(
            "Anonymized cancelled approvals after grace period, count: %d", len(archived_cancelled_approval)
        )
