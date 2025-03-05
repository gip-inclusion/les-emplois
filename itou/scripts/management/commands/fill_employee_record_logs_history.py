import collections
import datetime
import time

from django.contrib.admin import models as admin_models
from django.contrib.contenttypes.models import ContentType
from django.db.models import OuterRef, Q, Subquery

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordTransition, EmployeeRecordTransitionLog
from itou.utils.command import BaseCommand


BULK_CREATE_BATCH_SIZE = 1_000


def datetime_from_asp_batch_file(asp_batch_file):
    # RIAE_FS_20210512102743.json
    return datetime.datetime(*(time.strptime(asp_batch_file[8:-5], "%Y%m%d%H%M%S")[0:6]), tzinfo=datetime.UTC)


def find_log_entry_approximately_matching_datetime(dt, log_entries):
    if not dt or not log_entries:
        return False

    for log_entry in log_entries:
        if abs((dt - log_entry.action_time).total_seconds()) < 1.0:
            return log_entry
    return False


class Command(BaseCommand):
    def handle(self, **options):
        log_entries_by_object = collections.defaultdict(list)
        for entry in admin_models.LogEntry.objects.filter(
            action_flag=admin_models.CHANGE, content_type=ContentType.objects.get_for_model(EmployeeRecord)
        ):
            if entry.change_message != "[]":
                log_entries_by_object[int(entry.object_id)].append(entry)

        qs = (
            EmployeeRecord.objects.filter(
                Q(asp_processing_code__isnull=False)
                | Q(processed_at__isnull=False)
                | Q(status__in=[Status.NEW, Status.REJECTED, Status.DISABLED, Status.ARCHIVED])
            )
            .annotate(
                first_log_timestamp=Subquery(
                    EmployeeRecordTransitionLog.objects.filter(employee_record=OuterRef("pk"))
                    .order_by("timestamp")
                    .values("timestamp")[:1]
                )
            )
            .order_by("-updated_at")
        )
        print(f"Count: {qs.count()}/{EmployeeRecord.objects.count()}")

        transition_logs = []
        for employee_record in qs.iterator():
            employee_record_transitions = []
            matching_log_entry = find_log_entry_approximately_matching_datetime(
                employee_record.updated_at, log_entries_by_object.get(employee_record.pk)
            )

            if employee_record.asp_processing_code:
                wait_for_asp_respond_transition = EmployeeRecordTransitionLog(
                    transition=EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE,
                    from_state=Status.READY,
                    to_state=Status.SENT,
                    timestamp=datetime_from_asp_batch_file(employee_record.asp_batch_file),
                    employee_record=employee_record,
                    recovered=True,
                )
                wait_for_asp_respond_transition.set_asp_batch_information(
                    employee_record.asp_batch_file,
                    employee_record.asp_batch_line_number,
                    employee_record.archived_json,
                )
                employee_record_transitions.append(wait_for_asp_respond_transition)

                if employee_record.status_based_on_asp_processing_code is Status.REJECTED:
                    if employee_record.status == Status.REJECTED and not matching_log_entry:
                        reject_tl_timestamp = employee_record.updated_at
                    else:
                        # Make it happen (improbably) *after* EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE
                        reject_tl_timestamp = datetime_from_asp_batch_file(
                            employee_record.asp_batch_file
                        ) + datetime.timedelta(milliseconds=1)
                    reject_transition = EmployeeRecordTransitionLog(
                        transition=EmployeeRecordTransition.REJECT,
                        from_state=Status.SENT,
                        to_state=Status.REJECTED,
                        timestamp=reject_tl_timestamp,
                        employee_record=employee_record,
                        recovered=True,
                    )
                    reject_transition.set_asp_processing_information(
                        employee_record.asp_processing_code,
                        employee_record.asp_processing_label,
                        employee_record.archived_json,
                    )
                    employee_record_transitions.append(reject_transition)

            if employee_record.processed_at:
                process_transition = EmployeeRecordTransitionLog(
                    transition=EmployeeRecordTransition.PROCESS,
                    from_state=Status.SENT,
                    to_state=Status.PROCESSED,
                    timestamp=employee_record.processed_at,
                    employee_record=employee_record,
                    recovered=True,
                )
                if employee_record.status_based_on_asp_processing_code is Status.PROCESSED:
                    process_transition.set_asp_processing_information(
                        employee_record.asp_processing_code,
                        employee_record.asp_processing_label,
                        employee_record.archived_json,
                    )
                employee_record_transitions.append(process_transition)

            if not matching_log_entry:  # .updated_at can't be trusted if there is a matching log entry
                if employee_record.status == Status.ARCHIVED:
                    employee_record_transitions.append(
                        EmployeeRecordTransitionLog(
                            transition=EmployeeRecordTransition.ARCHIVE,
                            from_state=employee_record.status_based_on_asp_processing_code,
                            to_state=Status.ARCHIVED,
                            timestamp=employee_record.updated_at,
                            employee_record=employee_record,
                            recovered=True,
                        )
                    )
                elif employee_record.status == Status.DISABLED:
                    employee_record_transitions.append(
                        EmployeeRecordTransitionLog(
                            transition=EmployeeRecordTransition.DISABLE,
                            from_state=employee_record.status_based_on_asp_processing_code,
                            to_state=Status.DISABLED,
                            timestamp=employee_record.updated_at,
                            employee_record=employee_record,
                            recovered=True,
                        )
                    )
                elif employee_record.status == Status.NEW and employee_record.asp_processing_code:
                    employee_record_transitions.append(
                        EmployeeRecordTransitionLog(
                            transition=EmployeeRecordTransition.DISABLE,
                            from_state=employee_record.status_based_on_asp_processing_code,
                            to_state=Status.DISABLED,
                            # Make it happen (improbably) *before* EmployeeRecordTransition.ENABLE
                            timestamp=employee_record.updated_at - datetime.timedelta(milliseconds=1),
                            employee_record=employee_record,
                            recovered=True,
                        )
                    )
                    employee_record_transitions.append(
                        EmployeeRecordTransitionLog(
                            transition=EmployeeRecordTransition.ENABLE,
                            from_state=Status.DISABLED,
                            to_state=Status.NEW,
                            timestamp=employee_record.updated_at,
                            employee_record=employee_record,
                            recovered=True,
                        )
                    )

            # Only create transitions if they are before the first one known.
            # It's not perfect, but better have some missing than duplicates.
            transition_logs += [
                tl
                for tl in employee_record_transitions
                if not employee_record.first_log_timestamp
                or tl.timestamp.replace(second=0, microsecond=0)
                < employee_record.first_log_timestamp.replace(second=0, microsecond=0)
            ]

            if len(transition_logs) >= BULK_CREATE_BATCH_SIZE:
                objs = EmployeeRecordTransitionLog.objects.bulk_create(transition_logs, ignore_conflicts=True)
                print(f"{len(objs)} objects created")
                time.sleep(0.2)
                transition_logs = []

        if transition_logs:
            objs = EmployeeRecordTransitionLog.objects.bulk_create(transition_logs, ignore_conflicts=True)
            print(f"{len(objs)} objects created")
