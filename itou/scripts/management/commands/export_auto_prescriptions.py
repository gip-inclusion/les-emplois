from datetime import date

from django.db.models import F

from itou.common_apps.address.departments import DEPARTMENTS
from itou.companies.enums import CompanyKind
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.users.enums import KIND_EMPLOYER
from itou.utils.command import BaseCommand
from itou.utils.management_commands import XlsxExportMixin


class Command(XlsxExportMixin, BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(dest="start_at_min", type=date.fromisoformat, help="Approval start_at from date")
        parser.add_argument(dest="start_at_max", type=date.fromisoformat, help="Approval start_at to date")

    def handle(self, start_at_min, start_at_max, **kwargs):
        queryset = (
            JobApplication.objects.exclude(approval=None)
            .select_related(
                "approval",
                "job_seeker",
                "to_company__convention",
            )
            .filter(
                state=JobApplicationState.ACCEPTED,
                to_company__kind__in=[CompanyKind.ACI, CompanyKind.EI, CompanyKind.ETTI, CompanyKind.AI],
                eligibility_diagnosis__author_kind=KIND_EMPLOYER,
                eligibility_diagnosis__author_siae=F("to_company"),
                approval__start_at__range=[start_at_min, start_at_max],
            )
        )

        self.stdout.write(f"Found {queryset.count()} auto prescriptions")

        filename = f"auto_prescriptions_{start_at_min}_{start_at_max}.xlsx"

        headers = [
            "ID établissement",
            "SIRET établissement",
            "SIRET à la signature",
            "Type établissement",
            "Nom établissement",
            "Département établissement",
            "Nom département établissement",
            "Nom région établissement",
            "Numéro pass",
            "Date début pass",
            "Date fin pass",
            "ID candidat",
            "Prénom candidat",
            "Nom candidat",
            "Date d'embauche",
        ]

        data = [
            [
                ja.to_company.pk,
                ja.to_company.siret,
                ja.to_company.convention.siret_signature,
                ja.to_company.kind,
                ja.to_company.name,
                ja.to_company.department,
                DEPARTMENTS.get(ja.to_company.department, "Département inconnu"),
                ja.to_company.region,
                ja.approval.number,
                ja.approval.start_at,
                ja.approval.end_at,
                ja.job_seeker.pk,
                ja.job_seeker.first_name,
                ja.job_seeker.last_name,
                ja.hiring_start_at,
            ]
            for ja in queryset.iterator()
        ]

        self.export_to_xlsx(filename, headers, data)
