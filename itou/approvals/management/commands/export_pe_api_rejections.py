import datetime

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.approvals.models import Approval
from itou.utils.management_commands import XlsxExportMixin


class Command(XlsxExportMixin, BaseCommand):
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
            self.stdout.write("No rejected approvals")
            return

        log_datetime = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        filename = f"{log_datetime}-export_pe_api_rejections.xlsx"

        data = []
        for approval in rejected_approvals:
            # Use the same logic that Approval.notify_pole_emploi() to get the SIAE using the PASS.
            company = approval.jobapplication_set.accepted().order_by("-created_at").first().to_company
            data.append(
                [
                    approval.number,
                    approval.pe_notification_time.isoformat(sep=" "),
                    approval.pe_notification_exit_code,
                    approval.user.nir,
                    approval.user.jobseeker_profile.pole_emploi_id,
                    approval.user.last_name,
                    approval.user.first_name,
                    approval.user.birthdate.isoformat(),
                    company.kind,
                    company.name,
                    company.department,
                ]
            )

        headers = [
            "numero",
            "date_notification",
            "code_echec",
            "nir",
            "pole_emploi_id",
            "nom_naissance",
            "prenom",
            "date_naissance",
            "siae_type",
            "siae_raison_sociale",
            "siae_departement",
        ]

        self.export_to_xlsx(filename, headers, data)
