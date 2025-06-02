import csv
import os

from django.conf import settings
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

    def handle(self, **options):
        job_seekers = User.objects.filter(kind=UserKind.JOB_SEEKER).select_related("jobseeker_profile").order_by("pk")

        headers = [
            "ID",
            "prénom",
            "nom",
            "nir",
            "identifiant_ft",
            "date_de_naissance",
        ]

        def serialize_job_seeker(job_seeker):
            return [
                str(job_seeker.pk),
                job_seeker.first_name.capitalize(),
                job_seeker.last_name.upper(),
                job_seeker.jobseeker_profile.nir,
                job_seeker.jobseeker_profile.pole_emploi_id,
                job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y")
                if job_seeker.jobseeker_profile.birthdate
                else "",
            ]

        filename = f"gps_export_beneficiaires_{timezone.localtime().strftime('%Y-%m-%d_%H:%M')}.csv"

        path = f"{settings.EXPORT_DIR}/{filename}"
        os.makedirs(settings.EXPORT_DIR, exist_ok=True)

        with open(path, "w") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(headers)
            for job_seeker in job_seekers.iterator():
                writer.writerow(serialize_job_seeker(job_seeker))
