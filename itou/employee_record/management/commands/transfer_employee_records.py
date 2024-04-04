import paramiko
from django.conf import settings
from django.utils import timezone
from rest_framework.renderers import JSONRenderer
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.employee_record.enums import MovementType, Status
from itou.employee_record.exceptions import SerializationError
from itou.employee_record.mocks.fake_serializers import TestEmployeeRecordBatchSerializer
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import EmployeeRecordBatchSerializer
from itou.utils.iterators import chunks

from ...common_management import EmployeeRecordTransferCommand


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
            self.stdout.write(
                f"Employee records serialization error during upload, can't process.\n"
                f"You may want to use --preflight option to check faulty employee record objects.\n"
                f"Check batch details and error: {raw_batch=},\n{ex=}"
            )
            return
        except Exception as ex:
            # In any other case, bounce exception
            raise ex from Exception(f"Unhandled error during upload phase for batch: {raw_batch=}")
        else:
            if not remote_path:
                self.stdout.write("Could not upload file, exiting ...")
                return

            # - update employee record notifications status (to SENT)
            # - store in which file they have been seen
            if dry_run:
                self.stdout.write("DRY-RUN: Not *really* updating employee records statuses")
                return

            # Now that file is transferred, update employee records status (SENT)
            # and store in which file they have been sent
            renderer = JSONRenderer()
            for idx, employee_record in enumerate(employee_records, 1):
                employee_record.update_as_sent(
                    remote_path, idx, renderer.render(batch_data["lignesTelechargement"][idx - 1])
                )

    def _parse_feedback_file(self, feedback_file: str, batch: dict, dry_run: bool) -> int:
        """
        - Parse ASP response file,
        - Update status of employee records,
        - Update metadata for processed employee records.

        Returns the number of errors encountered
        """
        batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(feedback_file)
        record_errors = 0
        records = batch.get("lignesTelechargement")

        if not records:
            self.stdout.write(f"Could not get any employee record from file: {feedback_file}")
            return 1

        # Check for notification records :
        # Notifications are not mixed with employee records
        notification_number = 0

        for record in records:
            if record.get("typeMouvement") == MovementType.UPDATE:
                notification_number += 1

        if notification_number == len(records):
            self.stdout.write(
                f"File `{feedback_file}` is an update notifications file, passing.",
            )
            return 1

        for idx, raw_employee_record in enumerate(records, 1):
            line_number = raw_employee_record.get("numLigne")
            processing_code = raw_employee_record.get("codeTraitement")
            processing_label = raw_employee_record.get("libelleTraitement")

            self.stdout.write(f"Record: {line_number=}, {processing_code=}, {processing_label=}")

            if not line_number:
                self.stdout.write(f"No line number for employee record {idx=}, {feedback_file=}", idx, feedback_file)
                record_errors += 1
                continue

            # Now we must find the matching FS
            employee_record = EmployeeRecord.objects.find_by_batch(batch_filename, line_number).first()

            if not employee_record:
                self.stdout.write(f"Could not get existing employee record data: {batch_filename=}, {line_number=}")
                # Do not count as an error
                continue

            archived_json = JSONRenderer().render(raw_employee_record)
            # Employee record successfully processed by ASP :
            if processing_code == EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE:
                # Archive a JSON copy of employee record (with processing code and label)
                employee_record.asp_processing_code = processing_code
                employee_record.asp_processing_label = processing_label

                if not dry_run:
                    try:
                        if employee_record.status != Status.PROCESSED:
                            employee_record.update_as_processed(processing_code, processing_label, archived_json)
                        else:
                            self.stdout.write(f"Already accepted: {employee_record=}")
                    except Exception as ex:
                        self.stdout.write(
                            f"Can't update employee record : {employee_record=} {employee_record.status=} {ex=}"
                        )
                else:
                    self.stdout.write(f"DRY-RUN: Accepted {employee_record=}, {processing_code=}, {processing_label=}")
            else:
                # Employee record has already been processed : SKIP, not an error
                if employee_record.status == Status.PROCESSED:
                    # Do not update, keep it clean
                    self.stdout.write(f"Skipping, already accepted: {employee_record=}")
                    continue

                # Employee record has not been processed by ASP :
                if not dry_run:
                    # One special case added for support concerns:
                    # 3436 processing code are automatically converted as PROCESSED
                    if processing_code == EmployeeRecord.ASP_DUPLICATE_ERROR_CODE:
                        employee_record.status = Status.REJECTED
                        employee_record.asp_processing_code = EmployeeRecord.ASP_DUPLICATE_ERROR_CODE
                        employee_record.update_as_processed_as_duplicate(archived_json)

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
                                    status=Status.NEW,
                                    employee_record=employee_record,
                                    defaults={"updated_at": timezone.now},
                                )

                        continue

                    # Fixes unexpected stop on multiple pass on the same file
                    if employee_record.status != Status.REJECTED:
                        # Standard error / rejection processing
                        employee_record.update_as_rejected(processing_code, processing_label, archived_json)
                    else:
                        self.stdout.write(f"Already rejected: {employee_record=}")
                else:
                    self.stdout.write(f"DRY-RUN: Rejected {employee_record=}, {processing_code=}, {processing_label=}")

        return record_errors

    @monitor(monitor_slug="transfer-employee-records-download")
    def download(self, sftp: paramiko.SFTPClient, dry_run: bool):
        """Fetch and process feedback ASP files for employee records"""
        self.download_json_file(sftp, dry_run)

    @monitor(monitor_slug="transfer-employee-records-upload")
    def upload(self, sftp: paramiko.SFTPClient, dry_run: bool):
        """
        Upload a file composed of all ready employee records
        """
        self.stdout.write("Starting UPLOAD of employee records")
        ready_employee_records = EmployeeRecord.objects.filter(status=Status.READY)
        for batch in chunks(
            ready_employee_records, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS, max_chunk=self.MAX_UPLOADED_FILES
        ):
            self._upload_batch_file(sftp, batch, dry_run)

    def handle(self, *, upload, download, preflight, wet_run, asp_test=False, debug=False, **options):
        if preflight:
            self.stdout.write("Preflight activated, checking for possible serialization errors...")
            self.preflight(EmployeeRecord)
        elif upload or download:
            if not settings.ASP_FS_SFTP_HOST:
                self.stdout.write("Your environment is missing ASP_FS_SFTP_HOST to run this command.")
                return

            self.asp_test = asp_test
            if asp_test:
                self.stdout.write("Using *TEST* JSON serializers (SIRET number mapping)")

            with self.get_sftp_connection(debug=debug) as sftp:
                self.stdout.write(f'Connected to "{settings.ASP_FS_SFTP_HOST}" as "{settings.ASP_FS_SFTP_USER}"')
                self.stdout.write(f'''Current remote dir is "{sftp.normalize('.')}"''')

                # Send files to ASP
                if upload:
                    self.upload(sftp, not wet_run)

                # Fetch result files from ASP
                if download:
                    self.download(sftp, not wet_run)

            self.stdout.write("Employee records processing done!")
        else:
            self.stdout.write("No valid options (upload, download or preflight) were given")
