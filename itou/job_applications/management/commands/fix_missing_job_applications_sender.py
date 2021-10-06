from django.core.management.base import BaseCommand

from itou.job_applications.models import JobApplication


class Command(BaseCommand):
    """
    Fix missing `sender` field in JobApplication entries.

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
