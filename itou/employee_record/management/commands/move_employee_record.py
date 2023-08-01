from django.core.management.base import BaseCommand

from itou.approvals.models import Approval
from itou.employee_record.models import EmployeeRecord


class Command(BaseCommand):
    """
    Move employee record / job application from an SIAE to another:

    Useful when employee records / job applications are created with the wrong target SIAE.

    Conditions :
        - employee record has not be sent to ASP (ideally: NEW)
        - job application must be accepted (hiring)

    Process (for a given approval number) :
    - change most recent job application `to_siae` field to target SIAE
    - remove *non-processed* employee record linked to old SIAE
    - create a NEW (status) employee record for job application with new target SIAE
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run", dest="wet_run", action="store_true", help="Perform *real* employee record move operation"
        )
        parser.add_argument("--approval", dest="approval_number", help="Target approval (approval number)")
        parser.add_argument("--from-siae-id", dest="from_siae_id", help="Origin SIAE (PK)")
        parser.add_argument("--to-siae-id", dest="to_siae_id", help="Target SIAE (PK)")
        parser.add_argument(
            "--move-hiring", dest="move_hiring", action="store_true", help="Move job application to new structure"
        )

    def handle(self, *, approval_number, from_siae_id, to_siae_id, move_hiring, wet_run, **options):
        self.stdout.write("+ Move employee record from one SIAE to another")
        # Check approval validitu
        try:
            approval = Approval.objects.get(number=approval_number)
        except Approval.DoesNotExist:
            self.stderr.write(f"Approval {approval_number} does not exist")
            return

        self.stdout.write(f" - Approval number: {approval_number}")
        self.stdout.write(f" - From SIAE: {from_siae_id}")
        self.stdout.write(f" - To SIAE: {to_siae_id}")

        job_applications_qs = approval.jobapplication_set.filter(state="accepted")
        job_applications = job_applications_qs.filter(to_siae_id=from_siae_id)

        if (cnt := job_applications.count()) != 1:
            self.stderr.write(
                f"{cnt} job application(s) found for approval {approval_number} "
                f"and SIAE ID:{from_siae_id}. Fix this before running this script again."
            )
            if moved_qs := job_applications_qs.filter(to_siae_id=to_siae_id):
                self.stdout.write(
                    f"HINT: job application {moved_qs.first()} has already been moved to SIAE ID:{to_siae_id}"
                )
                er = EmployeeRecord.objects.filter(
                    approval_number=approval_number, job_application=moved_qs.first(), status="PROCESSED"
                )
                if er.count():
                    self.stdout.write(
                        f"HINT: check existing *processed* employee record(s) {list(er.values('pk'))}"
                        f" for this job application"
                    )
            return

        self.stdout.write(f" - Job application linked: {job_applications.first().pk}")

        try:
            er = EmployeeRecord.objects.get(
                approval_number=approval,
                job_application__to_siae_id=from_siae_id,
                status="NEW",
            )
        except EmployeeRecord.DoesNotExist:
            self.stderr.write(f"No employee record found for approval {approval_number}")

            if not move_hiring:
                return
            else:
                self.stdout.write(
                    f"Will move job application:{job_applications.first()} "
                    f"from SIAE ID:{from_siae_id} "
                    f"to SIAE ID:{to_siae_id}"
                )

        if wet_run:
            ja = er.job_application

            # 1 - update job applications with new SIAE
            self.stdout.write(f" - changing job application {ja.pk} SIAE to: {to_siae_id}")
            ja.to_siae_id = to_siae_id
            ja.save()

            # No use creating an employee record for an expired approval
            if not approval.is_valid:
                self.stderr.write(f"approval {approval_number} is not valid, can't recreate employee record")
                return

            # 2 - the old employee record must be deleted
            self.stdout.write(f" - deleting employee record: {er.pk}")
            er.delete()

            try:
                # 3 - attempt to recreate an employee record
                # this step can fail if the job seeker profile is not properly filled
                # however, SIAE members can recreate the employee record themselves
                self.stdout.write(f" - creating new employee record for job application {ja.pk}")
                EmployeeRecord.from_job_application(ja).save()
            except Exception as exc:
                self.stderr.write(f"Error while creating employee record: {exc}")
            else:
                self.stdout.write("+ Done!")
