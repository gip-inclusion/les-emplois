from django.utils import timezone

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.management_commands import XlsxExportMixin


class Command(BaseCommand, XlsxExportMixin):
    """
    Export job seekers from given deparment for GPS
    """

    help = "Export job seekers to give to FT in order to retrieve advisor contact information."

    def add_arguments(self, parser):
        parser.add_argument(
            "department",
            type=str,
            help="The department of the beneficiaries",
        )

    def handle(self, department, **options):
        job_seekers = (
            User.objects.filter(department=department, kind=UserKind.JOB_SEEKER)
            .select_related("jobseeker_profile")
            .order_by("pk")
        )

        headers = [
            "ID",
            "prénom",
            "nom",
            "nir",
            "date_de_naissance",
        ]

        data = [
            [
                str(job_seeker.pk),
                job_seeker.first_name.capitalize(),
                job_seeker.last_name.upper(),
                job_seeker.jobseeker_profile.nir,
                job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y")
                if job_seeker.jobseeker_profile.birthdate
                else "",
            ]
            for job_seeker in job_seekers
        ]
        filename = f"gps_dpt_{department}_{timezone.localtime().strftime('%Y-%m-%d_%H:%M')}.xlsx"
        self.export_to_xlsx(filename, headers, data)
