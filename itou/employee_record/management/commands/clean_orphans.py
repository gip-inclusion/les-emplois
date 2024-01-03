import django.db.transaction as transaction
from django.db.models import Count, F

from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @transaction.atomic()
    def handle(self, *, wet_run=False, **options):
        ja_with_multiple_er = (
            EmployeeRecord.objects.values("job_application")
            .annotate(cnt=Count("job_application"))
            .filter(cnt__gt=1)
            .values_list("job_application", flat=True)
        )
        print(f"Found {ja_with_multiple_er.count()} job applications with more than 1 employee record")
        for ja_pk in ja_with_multiple_er:
            all_related_er = EmployeeRecord.objects.filter(job_application=ja_pk)
            orphaned_er = all_related_er.orphans()

            # Fewer orphans than non-orphans, we can safely delete the orphans
            if orphaned_er.count() < all_related_er.count():
                print(f"Deleting all orphans for job_application={ja_pk}: {orphaned_er.values_list('pk', flat=True)}")
                if wet_run:
                    orphaned_er.delete()
                continue

            # Same numbers of orphans than non-orphans, keep the last one (probably :P)
            # Using `asp_batch_file` because it holds the timestamp of when it was sent while `updated_at` and
            # `created_at` can have been touched, putting nulls last to prefer employee records that were really sent.
            to_delete = orphaned_er.order_by(
                F("asp_batch_file").desc(nulls_last=True),
                "-updated_at",
                "-created_at",
            )[1:].values_list("pk", flat=True)  # fmt: skip
            print(f"Deleting oldest orphans for job_application={ja_pk}: {to_delete}")
            if wet_run:
                EmployeeRecord.objects.filter(pk__in=to_delete).delete()
