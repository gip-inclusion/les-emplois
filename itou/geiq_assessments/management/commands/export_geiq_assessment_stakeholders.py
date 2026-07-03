import csv
import datetime
import os

from django.conf import settings
from django.db.models import Prefetch
from django.utils import timezone

from itou.geiq_assessments.models import Assessment, AssessmentInstitutionLink
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    help = "Export GEIQ assessment stakeholders submitted on or after a given date."

    def add_arguments(self, parser):
        parser.add_argument(
            "submitted_since",
            type=datetime.date.fromisoformat,
            help="Only include assessments submitted on or after this date (ISO format, e.g. 2026-06-01).",
        )

    def handle(self, submitted_since, **options):
        if isinstance(submitted_since, str):
            submitted_since = datetime.date.fromisoformat(submitted_since)

        submitted_since_at = timezone.make_aware(datetime.datetime.combine(submitted_since, datetime.time.min))

        convention_links = AssessmentInstitutionLink.objects.filter(with_convention=True).select_related("institution")
        queryset = (
            Assessment.objects.filter(submitted_at__isnull=False, submitted_at__gte=submitted_since_at)
            .select_related("submitted_by", "reviewed_by", "final_reviewed_by")
            .prefetch_related(Prefetch("institution_links", queryset=convention_links, to_attr="convention_links"))
            .order_by("submitted_at")
        )

        count = queryset.count()
        self.stdout.write(f"Found {count} submitted assessments")
        if count == 0:
            return

        headers = [
            "Nom du GEIQ principal",
            "Email utilisateur GEIQ (transmis par)",
            "Email utilisateur DDETS/DREETS (contrôlé par)",
            "Email utilisateur DREETS (contrôlé par DREETS)",
            "Institution liée avec convention",
        ]

        filename = f"geiq_assessment_stakeholders_since_{submitted_since.isoformat()}.csv"
        path = f"{settings.EXPORT_DIR}/{filename}"
        os.makedirs(settings.EXPORT_DIR, exist_ok=True)

        with open(path, "w", newline="") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(headers)
            for assessment in queryset:
                writer.writerow(
                    [
                        assessment.label_geiq_name,
                        # submitted_by, reviewed_by, final_reviewed_by are Nullable
                        getattr(assessment.submitted_by, "email", ""),
                        getattr(assessment.reviewed_by, "email", ""),
                        getattr(assessment.final_reviewed_by, "email", ""),
                        ", ".join(link.institution.name for link in assessment.convention_links),
                    ]
                )

        self.stdout.write(f"CSV file created `{path}`")
