import paramiko
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.parsers import JSONParser
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.employee_record.common_management import EmployeeRecordTransferCommand, IgnoreFile
from itou.employee_record.enums import MovementType, NotificationStatus, Status
from itou.employee_record.exceptions import SerializationError
from itou.employee_record.mocks.fake_serializers import TestEmployeeRecordBatchSerializer
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import EmployeeRecordBatchSerializer
from itou.job_applications.enums import JobApplicationState
from itou.utils import asp as asp_utils
from itou.utils.iterators import chunks


class Command(EmployeeRecordTransferCommand):
    def _upload_batch_file(self, sftp: paramiko.SFTPClient, employee_records: list[EmployeeRecord], dry_run: bool):
        """
        Render a list of employee records in JSON format then send it to SFTP upload folder
        """
        raw_batch = EmployeeRecordBatch(employee_records)
        # Ability to use ASP test serializers (using fake SIRET numbers)
        if self.asp_test:
            batch_data = TestEmployeeRecordBatchSerializer(raw_batch).data
        else:
            batch_data = EmployeeRecordBatchSerializer(raw_batch).data

        try:
            remote_path = self.upload_json_file(batch_data, sftp, dry_run)
        except SerializationError as ex:
            self.logger.error(
                "Employee records serialization error during upload, can't process.\n"
                "You may want to use --preflight option to check faulty employee record objects.\n"
                "Check batch details and error: raw_batch=%s,\nex=%s",
                raw_batch,
                ex,
            )
            return
        except Exception as ex:
            # In any other case, bounce exception
            raise ex from Exception(f"Unhandled error during upload phase for batch: {raw_batch=}")
        else:
            if not remote_path:
                self.logger.warning("Could not upload file, exiting ...")
                return

            # - update employee record notifications status (to SENT)
            # - store in which file they have been seen
            if dry_run:
                self.logger.info("DRY-RUN: Not *really* updating employee records statuses")
                return

            # Now that file is transferred, update employee records status (SENT)
            # and store in which file they have been sent
            for idx, employee_record in enumerate(employee_records, 1):
                employee_record.wait_for_asp_response(
                    file=remote_path,
                    line_number=idx,
                    archive=batch_data["lignesTelechargement"][idx - 1],
                )

    def _parse_feedback_file(self, feedback_file: str, batch: dict, dry_run: bool) -> None:
        """
        - Parse ASP response file,
        - Update status of employee records,
        - Update metadata for processed employee records.
        """
        batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(feedback_file)

        for idx, raw_employee_record in enumerate(batch["lignesTelechargement"], 1):
            # UPDATE notifications are sent in specific files and are not mixed
            # with "standard" employee records (CREATION).
            if raw_employee_record.get("typeMouvement") != MovementType.CREATION:
                raise IgnoreFile(f"Received 'typeMouvement' is not {MovementType.CREATION}")

            line_number = raw_employee_record["numLigne"]
            processing_code = raw_employee_record["codeTraitement"]
            processing_label = raw_employee_record["libelleTraitement"]
            self.logger.info(f"Record: {line_number=}, {processing_code=}, {processing_label=}")

            # Now we must find the matching FS
            employee_record = EmployeeRecord.objects.find_by_batch(batch_filename, line_number).first()
            if not employee_record:
                self.logger.info(
                    f"Skipping, could not get existing employee record: {batch_filename=}, {line_number=}"
                )
                # Do not count as an error
                continue
            if employee_record.status in [Status.PROCESSED, Status.REJECTED]:
                self.logger.info(f"Skipping, employee record is already {employee_record.status}")
                continue
            if employee_record.status != Status.SENT:
                self.logger.info(f"Skipping, incoherent status for {employee_record=}")
                continue

            if processing_code == EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE:  # Processed by ASP
                if not dry_run:
                    employee_record.process(code=processing_code, label=processing_label, archive=raw_employee_record)
                else:
                    self.logger.info(f"DRY-RUN: Accepted {employee_record=}, {processing_code=}, {processing_label=}")
            else:  # Rejected by ASP
                if not dry_run:
                    # One special case added for support concerns:
                    # 3436 processing code are automatically converted as PROCESSED
                    if processing_code == EmployeeRecord.ASP_DUPLICATE_ERROR_CODE:
                        employee_record.process(
                            code=processing_code,
                            label=processing_label,
                            archive=raw_employee_record,
                            as_duplicate=True,
                        )

                        # If the ASP mark the employee record as duplicate,
                        # and there is a suspension or a prolongation for the associated approval,
                        # then we create a notification to be sure the ASP has the correct end date.
                        try:
                            approval = Approval.objects.get(number=employee_record.approval_number)
                        except Approval.DoesNotExist:
                            pass  # No point to send a notification about an approval if it doesn't exist
                        else:
                            if approval.suspension_set.exists() or approval.prolongation_set.exists():
                                # Mimic the SQL trigger function "create_employee_record_notification()"
                                EmployeeRecordUpdateNotification.objects.update_or_create(
                                    status=NotificationStatus.NEW,
                                    employee_record=employee_record,
                                    defaults={"updated_at": timezone.now},
                                )

                        continue

                    employee_record.reject(code=processing_code, label=processing_label, archive=raw_employee_record)
                else:
                    self.logger.info(f"DRY-RUN: Rejected {employee_record=}, {processing_code=}, {processing_label=}")

    @monitor(
        monitor_slug="transfer-employee-records-download",
        monitor_config={
            "schedule": {"type": "crontab", "value": "25 8-18/2 * * 1-5"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def download(self, sftp: paramiko.SFTPClient, dry_run: bool):
        """Fetch and process feedback ASP files for employee records"""
        self.download_json_file(sftp, dry_run)

    @monitor(
        monitor_slug="transfer-employee-records-upload",
        monitor_config={
            "schedule": {"type": "crontab", "value": "55 8-18/2 * * 1-5"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def upload(self, sftp: paramiko.SFTPClient, dry_run: bool):
        """
        Upload a file composed of all ready employee records
        """
        self.logger.info("Starting UPLOAD of employee records")
        employee_records_to_send = EmployeeRecord.objects.filter(
            status=Status.READY, job_application__state=JobApplicationState.ACCEPTED
        ).order_by("updated_at")
        for batch in chunks(
            employee_records_to_send, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS, max_chunk=self.MAX_UPLOADED_FILES
        ):
            self._upload_batch_file(sftp, batch, dry_run)

    def handle(self, *, upload, download, parse_file=None, preflight, wet_run, asp_test=False, debug=False, **options):
        if preflight:
            self.logger.info("Preflight activated, checking for possible serialization errors...")
            self.preflight(EmployeeRecord)
        elif parse_file:
            # If we need to manually parse a feedback file then we probably have some kind of unexpected state,
            # so use an atomic block to avoid creating more incoherence when something breaks.
            with transaction.atomic():
                self._parse_feedback_file(parse_file.name, JSONParser().parse(parse_file), dry_run=not wet_run)
        elif upload or download:
            if not settings.ASP_SFTP_HOST:
                self.logger.info("Your environment is missing ASP_SFTP_HOST to run this command.")
                return

            self.asp_test = asp_test
            if asp_test:
                self.logger.info("Using *TEST* JSON serializers (SIRET number mapping)")

            with asp_utils.get_sftp_connection() as sftp:
                self.logger.info(f'Connected to "{settings.ASP_SFTP_HOST}" as "{settings.ASP_SFTP_USER}"')
                self.logger.info(f'''Current remote dir is "{sftp.normalize(".")}"''')

                # Send files to ASP
                if upload:
                    self.upload(sftp, not wet_run)

                # Fetch result files from ASP
                if download:
                    self.download(sftp, not wet_run)

            self.logger.info("Employee records processing done!")
        else:
            self.logger.info("No valid options (upload, download or preflight) were given")
