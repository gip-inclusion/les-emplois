import csv
import datetime
import os

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand

from itou.approvals.models import Approval


class Command(BaseCommand):
    def handle(self, **options):

        first_day_of_month = datetime.date.today().replace(day=1)
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

        writer = csv.writer(self.stdout, lineterminator=os.linesep)

        if rejected_approvals:
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
                ],
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
                ],
            )
