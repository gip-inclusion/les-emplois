import csv
import datetime
import os

from django.core.management.base import BaseCommand
from django.db.models import F

from itou.common_apps.address.departments import DEPARTMENTS
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.enums import SiaeKind
from itou.users.enums import KIND_SIAE_STAFF


class Command(BaseCommand):
    def handle(self, **kwargs):
        writer = csv.writer(self.stdout, lineterminator=os.linesep)
        queryset = (
            JobApplication.objects.exclude(approval=None)
            .select_related(
                "approval",
                "job_seeker",
                "to_siae__convention",
            )
            .filter(
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                to_siae__kind__in=[SiaeKind.ACI, SiaeKind.EI, SiaeKind.ETTI, SiaeKind.AI],
                eligibility_diagnosis__author_kind=KIND_SIAE_STAFF,
                eligibility_diagnosis__author_siae=F("to_siae"),
                approval__start_at__range=[datetime.date(2022, 1, 1), datetime.date(2022, 10, 1)],
            )
        )

        writer.writerow(
            [
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
            ],
        )

        for ja in queryset.iterator():
            writer.writerow(
                [
                    ja.to_siae.pk,
                    ja.to_siae.siret,
                    ja.to_siae.convention.siret_signature,
                    ja.to_siae.kind,
                    ja.to_siae.name,
                    ja.to_siae.department,
                    DEPARTMENTS.get(ja.to_siae.department, "Département inconnu"),
                    ja.to_siae.region,
                    ja.approval.number,
                    ja.approval.start_at,
                    ja.approval.end_at,
                    ja.job_seeker.pk,
                    ja.job_seeker.first_name,
                    ja.job_seeker.last_name,
                    ja.hiring_start_at,
                ],
            )
