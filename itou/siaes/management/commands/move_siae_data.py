# pylint: disable=consider-using-f-string

import argparse

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef, Subquery
from django.utils import timezone

from itou.approvals import models as approvals_models
from itou.eligibility import models as eligibility_models
from itou.invitations import models as invitations_models
from itou.job_applications import models as job_applications_models
from itou.siae_evaluations.models import EvaluatedSiae
from itou.siaes import models as siaes_models
from itou.users import models as users_models


HELP_TEXT = """
    Move all data from siae A to siae B (or only the job applications if `only-job-applications` option is set).
    After this move siae A is no longer supposed to be used or even accessible.
    Members of siae A are detached, geolocalization is removed and new job applications are blocked.

    This command should be used when users have been using the wrong siae A instead of using the correct siae B.

    Siae A is *not* deleted at the end. This is because it might not always be possible or make sense to do so
    and because cleaning up irrelevant siaes is actually the job of the import_siae command.

    You will most likely still have manual actions to do after the move, typically deactivating the convention
    of siae A. That one cannot be automated because it has drastic consequences as it disables all siaes of the
    same convention. So be sure to read your trello ticket instructions thoroughly and don't assume this command
    does everything.

    Examples of use in local dev:
    $ make django_admin COMMAND="move_siae_data --from 3243 --to 9612"
    $ make django_admin COMMAND="move_siae_data --from 3243 --to 9612 --only-job-applications"

    And in production:
    $ cd && cd app_* && django-admin move_siae_data --from 3243 --to 9612 --wet-run
"""


class Command(BaseCommand):
    help = HELP_TEXT

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_id",
            metavar="FROM",
            type=int,
            help="ID of the siae to move data from.",
            required=True,
        )
        parser.add_argument(
            "--to",
            dest="to_id",
            metavar="TO",
            type=int,
            help="ID of the the siae to move data to.",
            required=True,
        )
        parser.add_argument(
            "--only-job-applications",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Set to True to move only job applications, nothing else!",
        )
        parser.add_argument("--wet-run", action=argparse.BooleanOptionalAction, default=False)

    def handle(self, from_id, to_id, wet_run=False, only_job_applications=False, **options):
        if from_id == to_id:
            self.stderr.write("Unable to use the same siae as source and destination (ID %s)\n" % from_id)
            return

        from_siae_qs = siaes_models.Siae.objects.filter(pk=from_id)
        try:
            from_siae = from_siae_qs.get()
        except siaes_models.Siae.DoesNotExist:
            self.stderr.write("Unable to find the siae ID %s\n" % from_id)
            return

        to_siae_qs = siaes_models.Siae.objects.filter(pk=to_id)
        try:
            to_siae = to_siae_qs.get()
        except siaes_models.Siae.DoesNotExist:
            self.stderr.write("Unable to find the siae ID %s\n" % to_id)
            return

        # Intermediate variable for better readability
        move_all_data = not only_job_applications

        self.stdout.write(
            "MOVE %s OF siae.id=%s - %s %s - %s\n"
            % (
                "DATA" if move_all_data else "JOB APPLICATIONS",
                from_siae.pk,
                from_siae.kind,
                from_siae.siret,
                from_siae.display_name,
            )
        )

        job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=from_id)
        self.stdout.write("| Job applications sent: %s" % job_applications_sent.count())

        job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=from_id)
        self.stdout.write("| Job applications received: %s" % job_applications_received.count())

        if move_all_data:
            # Move Job Description not already present in siae destination, Job Applications
            # related will be attached to Job Description present in siae destination
            appellation_subquery = Subquery(
                siaes_models.SiaeJobDescription.objects.filter(
                    siae_id=to_id, appellation_id=OuterRef("appellation_id")
                )
            )
            job_descriptions = siaes_models.SiaeJobDescription.objects.filter(siae_id=from_id).exclude(
                Exists(appellation_subquery)
            )
            self.stdout.write("| Job descriptions: %s\n" % job_descriptions.count())

            # Move users not already present in siae destination
            members = siaes_models.SiaeMembership.objects.filter(siae_id=from_id).exclude(
                user__in=users_models.User.objects.filter(siaemembership__siae_id=to_id)
            )
            self.stdout.write("| Members: %s\n" % members.count())

            diagnoses = eligibility_models.EligibilityDiagnosis.objects.filter(author_siae_id=from_id)
            self.stdout.write("| Diagnoses: %s\n" % diagnoses.count())

            prolongations = approvals_models.Prolongation.objects.filter(declared_by_siae_id=from_id)
            self.stdout.write("| Prolongations: %s\n" % prolongations.count())

            suspensions = approvals_models.Suspension.objects.filter(siae_id=from_id)
            self.stdout.write("| Suspensions: %s\n" % suspensions.count())

            # Don't move invitations for existing members
            # The goal is to keep information about the original information
            invitations = invitations_models.SiaeStaffInvitation.objects.filter(siae_id=from_id).exclude(
                email__in=users_models.User.objects.filter(siaemembership__siae_id=to_id).values_list(
                    "email", flat=True
                )
            )
            self.stdout.write("| Invitations: %s\n" % invitations.count())

            evaluated_siaes = EvaluatedSiae.objects.filter(siae_id=from_id)
            self.stdout.write("| Evaluated siaes: %s\n" % evaluated_siaes.count())

        self.stdout.write(
            "INTO siae.id=%s - %s %s - %s\n" % (to_siae.pk, to_siae.kind, to_siae.siret, to_siae.display_name)
        )

        dest_siae_job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=to_id)
        self.stdout.write("| Job applications sent: %s\n" % dest_siae_job_applications_sent.count())

        dest_siae_job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=to_id)
        self.stdout.write("| Job applications received: %s\n" % dest_siae_job_applications_received.count())

        if move_all_data:
            self.stdout.write(f"| Brand '{to_siae.brand}' will be updated with '{from_siae.display_name}'\n")
            self.stdout.write(
                f"| Description \n{to_siae.description}\nwill be updated with\n{from_siae.description}\n"
            )
            self.stdout.write(f"| Phone '{to_siae.phone}' will be updated with '{from_siae.phone}'\n")
            self.stdout.write(f"| Coords '{to_siae.coords}' will be updated with '{from_siae.coords}'\n")
            self.stdout.write(
                f"| Geoscore '{to_siae.geocoding_score}' will be updated with '{from_siae.geocoding_score}'\n"
            )

        if not wet_run:
            self.stdout.write("Nothing to do in dry run mode.\n")
            return

        with transaction.atomic():

            # If we move the job applications without moving the job descriptions as well, we need to unlink them,
            # as job applications will be attached to siae B but job descriptions will stay attached to siae A.
            if only_job_applications:
                for job_application in job_applications_sent:
                    job_application.selected_jobs.clear()
                for job_application in job_applications_received:
                    job_application.selected_jobs.clear()

            # If we move job_description, we have to take care of existant job_description linked
            # to siae B (destination), because we can't have 2 job_applications with the same Appellation
            # for one siae. Job applications linked to these kind of job_description have to be
            # unlinked to be transfered. Job_description can be different enough to be irrelevant.
            if move_all_data:
                # find Appellation linked to job_description siae B
                to_siae_appellation_id = siaes_models.SiaeJobDescription.objects.filter(siae_id=to_id).values_list(
                    "appellation_id", flat=True
                )

                # find job_applications in siae A, linked with job_description which Appellation is found in siae B
                job_applications_to_clear = job_applications_models.JobApplication.objects.filter(
                    to_siae_id=from_id,
                    selected_jobs__in=siaes_models.SiaeJobDescription.objects.filter(
                        siae_id=from_id, appellation_id__in=to_siae_appellation_id
                    ),
                )

                # clean job_applications to let them be transfered in siae B
                for job_application in job_applications_to_clear:
                    job_application.selected_jobs.clear()

            job_applications_sent.update(sender_siae_id=to_id)
            job_applications_received.update(to_siae_id=to_id)

            if move_all_data:
                # do not move duplicated job_descriptions
                job_descriptions.exclude(appellation_id__in=to_siae_appellation_id).update(siae_id=to_id)
                members.update(siae_id=to_id)
                diagnoses.update(author_siae_id=to_id)
                prolongations.update(declared_by_siae_id=to_id)
                suspensions.update(siae_id=to_id)
                invitations.update(siae_id=to_id)
                evaluated_siaes.update(siae_id=to_id)
                to_siae_qs.update(
                    brand=from_siae.display_name,
                    description=from_siae.description,
                    phone=from_siae.phone,
                    coords=from_siae.coords,
                    geocoding_score=from_siae.geocoding_score,
                )
                from_siae_qs.update(
                    block_job_applications=True,
                    job_applications_blocked_at=timezone.now(),
                    # Make sure the old siae no longer appears in results
                    coords=None,
                    geocoding_score=None,
                )

        self.stdout.write(
            "MOVE %s OF siae.id=%s FINISHED\n" % ("DATA" if move_all_data else "JOB APPLICATIONS", from_siae.pk)
        )
        orig_job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=from_id)
        self.stdout.write("| Job applications sent: %s\n" % orig_job_applications_sent.count())

        orig_job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=from_id)
        self.stdout.write("| Job applications received: %s\n" % orig_job_applications_received.count())

        self.stdout.write("INTO siae.id=%s\n" % to_siae.pk)

        dest_siae_job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_siae_id=to_id)
        self.stdout.write("| Job applications sent: %s\n" % dest_siae_job_applications_sent.count())

        dest_siae_job_applications_received = job_applications_models.JobApplication.objects.filter(to_siae_id=to_id)
        self.stdout.write("| Job applications received: %s\n" % dest_siae_job_applications_received.count())
