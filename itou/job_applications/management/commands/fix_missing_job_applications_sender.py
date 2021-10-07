from django.core.management.base import BaseCommand

from itou.job_applications.models import JobApplication


class Command(BaseCommand):
    """
    Fix missing `sender` field in JobApplication entries.

    Half of the cases where caused by `deduplicate_job_seekers`.
    But 1631 cases were existing before the first run:

    * 1631 cases before 16/09/2021 (1st run)
    * 3180 cases before 02/10/2021 (2nd run)
    * 3288 cases before running this fix
    * 1629 cases after running this fix \o/

    Some cases cannot be fixed by this fix.

    This is temporary and should be deleted after having been
    run in production.

    Query:
        select
            *
        from
            job_applications_jobapplication
        where
            sender_id is null
        order by
            created_at

    To debug:
        django-admin fix_missing_job_applications_sender --dry-run

    To populate the database:
        django-admin fix_missing_job_applications_sender
    """

    help = "Fix missing `sender` field in JobApplication entries."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only print data to fix")

    def handle(self, dry_run=False, **options):

        job_apps_without_sender = JobApplication.objects.filter(sender__isnull=True)

        self.stdout.write("-" * 80)
        self.stdout.write(f"{job_apps_without_sender.count()} job applications without `sender`.")

        for job_app in job_apps_without_sender:

            if job_app.sender_kind == job_app.SENDER_KIND_JOB_SEEKER:
                job_app.sender = job_app.job_seeker

            elif job_app.sender_kind == job_app.SENDER_KIND_PRESCRIBER:
                try:
                    job_app.sender = job_app.sender_prescriber_organization.active_admin_members.first()
                except AttributeError:
                    # Some cases cannot be fixed by this fix, mostly pre-existing cases.
                    self.stdout.write(
                        f"Unable to find a `sender` for {job_app.pk} since it has no `sender_prescriber_organization`."
                    )

            elif job_app.sender_kind == job_app.SENDER_KIND_SIAE_STAFF:
                job_app.sender = job_app.sender_siae.active_admin_members.first()

            if not dry_run:
                job_app.save()

        unfixable_job_apps_without_sender = JobApplication.objects.filter(sender__isnull=True)
        self.stdout.write(f"Unable to fix {unfixable_job_apps_without_sender.count()} job applications.")

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
