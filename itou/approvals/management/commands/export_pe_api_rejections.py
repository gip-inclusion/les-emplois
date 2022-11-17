import csv
import datetime
import os

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.approvals.models import Approval


class Command(BaseCommand):
    def handle(self, **options):

        first_day_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rejected_approvals = (
            Approval.objects.filter(
                pe_notification_status="notification_error",
                pe_notification_time__range=[
                    first_day_of_month - relativedelta(months=1),
                    first_day_of_month,
                ],
            )
            .select_related("user")
            .order_by("pe_notification_time")
        )

        if not rejected_approvals:
            self.stdout.write("No rejected approvels")
            return

        log_datetime = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        path = f"{settings.EXPORT_DIR}/{log_datetime}-export_pe_api_rejections.csv"
        os.makedirs(settings.EXPORT_DIR, exist_ok=True)

        with open(path, "w") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "numero",
                    "date_notification",
                    "code_echec",
                    "nir",
                    "pole_emploi_id",
                    "nom_naissance",
                    "prenom",
                    "date_naissance",
                    "siae_departement",
                ]
            )

            for approval in rejected_approvals:
                # Use the same logic that Approval.notify_pole_emploi() to get the SIAE using the PASS.
                siae = approval.jobapplication_set.accepted().order_by("-created_at").first().to_siae
                writer.writerow(
                    [
                        approval.number,
                        approval.pe_notification_time,
                        approval.pe_notification_exit_code,
                        approval.user.nir,
                        approval.user.pole_emploi_id,
                        approval.user.last_name,
                        approval.user.first_name,
                        approval.user.birthdate,
                        siae.department,
                    ]
                )

        self.stdout.write(f"CSV file created `{path}`")
