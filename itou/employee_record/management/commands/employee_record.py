import argparse
import uuid

from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.utils.command import BaseCommand, dry_runnable


class Command(BaseCommand):
    """Utilities for employee records.

    ### create
    Cas général : une SIAE a besoin de transférer un PASS pour un SIRET différent de l'actuel.
    Solution : Créer une FS avec le SIRET désiré via `create` et la transmettre automatiquement avec `--ready`.

    Cas d'exemples :
        1. Une SIAE a changé de SIRET en cours d'année et a besoin de transférer sur son ancien SIRET pour la période
            avant le changement, la FS actuelle est utilisée pour le nouveau SIRET, on ne veut pas y toucher.
           Solution : On crée la FS sur la candidature existante et avec l'ancien SIRET, on attend son intégration,
            on la supprime pour ne pas avoir un doublon de FS et interférer avec la FS portant le SIRET actuel.

        2. Une SIAE se retrouve découpée en plusieurs structures, et a besoin de transférer sur le nouveau et/ou pour
            plusieurs SIRET, mais une seule candidature existe et elle est sur l'ancien SIRET.
           Solution : On crée la FS sur la candidature existante et avec l'ancien SIRET, on attend son intégration,
            on passe la FS en "Archivée" car le PASS est déjà expiré donc autant garder la trace de l'envoi vu que ce
            n'est pas gênant.
    """

    ATOMIC_HANDLE = True

    def add_arguments(self, parser: argparse.ArgumentParser):
        super().add_arguments(parser)
        subparsers = parser.add_subparsers(dest="command", required=True)

        create = subparsers.add_parser("create")
        create.add_argument("job_application", type=uuid.UUID)
        create.add_argument("--siret")
        create.add_argument("--ready", action="store_true")
        create.add_argument("--wet-run", action="store_true")

        resend = subparsers.add_parser("resend")
        resend.add_argument("employee_record", type=int)
        resend.add_argument("--unarchive", action="store_true")
        resend.add_argument("--wet-run", action="store_true")

    def create(self, *, job_application, siret, ready, wet_run):
        employee_record = EmployeeRecord(job_application=JobApplication.objects.get(pk=job_application))
        employee_record._fill_denormalized_fields()
        if siret is not None:
            # In some edge cases we need to send an employee record for an old/previous SIRET but don't want to mess
            # with the existing one (i.e. already processed by the ASP)
            employee_record.siret = siret
        employee_record.save()

        if ready:
            employee_record.ready(save=False)
            if siret is not None:
                # This needs to be done again because ready() call _fill_denormalized_fields() which reset the SIRET
                employee_record.siret = siret
            employee_record.save()

    def resend(self, *, employee_record, unarchive, wet_run):
        employee_record = EmployeeRecord.objects.get(pk=employee_record)
        if unarchive:
            employee_record.unarchive()
        employee_record.ready()

    @dry_runnable
    def handle(self, *, command, **options):
        match command:
            case "create":
                self.create(
                    job_application=options["job_application"],
                    siret=options["siret"],
                    ready=options["ready"],
                    wet_run=options["wet_run"],
                )
            case "resend":
                self.resend(
                    employee_record=options["employee_record"],
                    unarchive=options["unarchive"],
                    wet_run=options["wet_run"],
                )
