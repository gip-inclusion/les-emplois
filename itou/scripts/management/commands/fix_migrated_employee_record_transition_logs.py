import datetime
import itertools

from django.core.cache import caches
from django.db.models import Exists, OuterRef, Prefetch
from itoutils.django.commands import dry_runnable

from itou.employee_record.models import (
    EmployeeRecord,
    EmployeeRecordTransition,
    EmployeeRecordTransitionLog,
)
from itou.utils.command import BaseCommand


LAST_MIGRATED_EMPLOYEE_RECORD_PK = 223234


class Command(BaseCommand):
    """Fix the EmployeeRecordTransitionLog migrated with inconsistent timestamps"""

    ATOMIC_HANDLE = True
    BATCH_SIZE = 1_000

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @dry_runnable
    def handle(self, **options):
        failsafe_cache = caches["failsafe"]
        cache_key = "fix_migrate_employee_record_update_notifications-last_record_pk"
        last_run_pk = failsafe_cache.get(cache_key) or 0
        self.logger.info("Starting fixing transition logs of employee records - starting at pk=%d", last_run_pk)

        MODIFICATION_TRANSITIONS = (
            EmployeeRecordTransition.PROCESS_MODIFICATION,
            EmployeeRecordTransition.REJECT_MODIFICATION,
            EmployeeRecordTransition.SCHEDULE_MODIFICATION,
            EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
        )

        records_to_check = list(
            EmployeeRecord.objects.filter(pk__gt=last_run_pk, pk__lte=LAST_MIGRATED_EMPLOYEE_RECORD_PK)
            .filter(
                Exists(
                    EmployeeRecordTransitionLog.objects.filter(
                        employee_record_id=OuterRef("pk"),
                        recovered=True,
                        transition__in=MODIFICATION_TRANSITIONS,
                    )
                )
            )
            .prefetch_related(
                Prefetch(
                    "logs",
                    queryset=EmployeeRecordTransitionLog.objects.filter(
                        transition__in=MODIFICATION_TRANSITIONS,
                        recovered=True,
                    ).order_by("pk"),
                    to_attr="modification_transitions",
                )
            )
            .order_by("pk")[: self.BATCH_SIZE]
        )

        logs_to_update = []
        for employee_record in records_to_check:
            if len(employee_record.modification_transitions) % 3 != 0:
                # Those logs have been created 3 by 3
                self.logger.error("Something is off with employee_record=%d", employee_record.pk)
                continue
            for trio in itertools.batched(employee_record.modification_transitions, 3, strict=True):
                if (log_to_fix := self.fix_trio(trio)) is not None:
                    logs_to_update.append(log_to_fix)
        EmployeeRecordTransitionLog.objects.bulk_update(logs_to_update, fields={"timestamp"})
        self.logger.info(
            "Checked %d EmployeeRecord and fixed %d EmployeeRecordTransitionLog",
            len(records_to_check),
            len(logs_to_update),
        )
        # When all employee records have been processed, restart from 0 to handle newly created notifications
        last_migrated_pk = records_to_check[-1].pk if records_to_check else 0
        failsafe_cache.set(cache_key, last_migrated_pk, timeout=datetime.timedelta(days=1).total_seconds())
        self.logger.info("Stored last migrated employee record - pk=%d", last_migrated_pk)

    def fix_trio(self, logs):
        schedule_log, wait_log, final_log = logs
        if (
            schedule_log.transition != EmployeeRecordTransition.SCHEDULE_MODIFICATION
            or wait_log.transition != EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE
            or final_log.transition
            not in (EmployeeRecordTransition.PROCESS_MODIFICATION, EmployeeRecordTransition.REJECT_MODIFICATION)
        ):
            self.logger.error("Something is off with employee_record=%d", schedule_log.employee_record.pk)
            return
        if final_log.timestamp < wait_log.timestamp:
            final_log.timestamp = wait_log.timestamp + datetime.timedelta(milliseconds=1)
            return final_log
        return
