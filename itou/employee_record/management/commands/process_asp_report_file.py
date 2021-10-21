import json
import logging
import os.path as os_path

from django.core.management.base import BaseCommand
from rest_framework.renderers import JSONRenderer

from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch
from itou.employee_record.serializers import EmployeeRecordSerializer


class Command(BaseCommand):
    """
    Manually processed an employee record ASP report file
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)

    def add_arguments(self, parser):
        """
        Command line arguments
        """
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Just parse employee records, do not update"
        )
        parser.add_argument("--file", dest="input_file", type=open, required=True, help="ASP input file")

    def handle(self, *args, **options):
        """
        Employee Record Management Command
        """
        input_file = options.get("input_file")
        renderer = JSONRenderer()

        with open(input_file.name, "r") as f:
            data = json.load(f)
            filename = os_path.basename(f.name)
            batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(filename)
            cnt = 0
            asp_success_code = "0000"

            self.logger.info("Start processing of ASP file: %s", batch_filename)

            records = data.get("lignesTelechargement")
            for idx, employee_record in enumerate(records, 1):
                line_number = employee_record.get("numLigne")
                processing_code = employee_record.get("codeTraitement")
                processing_label = employee_record.get("libelleTraitement")
                employee_record = EmployeeRecord.objects.find_by_batch(batch_filename, line_number).first()

                if not employee_record:
                    self.logger.info(
                        "Could not find employee record for file: %s, line: %s", batch_filename, line_number
                    )

                # If and only if SENT :
                if employee_record.status == EmployeeRecord.Status.SENT:
                    serializer = EmployeeRecordSerializer(employee_record)

                    self.logger.info("Processing employee record: %s", employee_record)
                    self.logger.info("Current status: %s", employee_record.status)
                    self.logger.info("Line number: %s", line_number)
                    self.logger.info("Processing code: %s", processing_code)
                    self.logger.info("Processing label: %s", processing_label)

                    if processing_code == asp_success_code:
                        # Correctly processed:
                        self.logger.info("Succesfully processed : closing")
                        employee_record.update_as_accepted(
                            processing_code, processing_label, renderer.render(serializer.data).decode()
                        )
                        cnt += 1
                    elif processing_code == "3436":
                        # Dups already processed by ASP:
                        self.logger.info("Already processed by ASP (dup) : closing")
                        employee_record.update_as_accepted(
                            asp_success_code, "INTEGRATION PLATEFORME", renderer.render(serializer.data).decode()
                        )
                        cnt += 1
                    else:
                        # "Normal" error case
                        self.logger.info("Updating as REJECTED with error code: %s", processing_code)
                        employee_record.update_as_rejected(processing_code, processing_label)
                        cnt += 1

                    self.logger.info("---")

            if cnt > 0:
                self.logger.info("Processed / fixed %s employee record(s)", cnt)

            self.logger.info("Finished processing of ASP file: %s", batch_filename)
