
from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE, geolocate_qs
from itou.companies.models import Company
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=["companies", "job-seekers"])
        parser.add_argument("--reliance-score", default=BAN_API_RELIANCE_SCORE, type=float, dest="reliance_score")
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
        )

    def handle(self, *, mode, wet_run, reliance_score, **options):
        match mode:
            case "companies":
                qs = Company.objects.all()
            case "job-seekers":
                qs = User.objects.filter(kind=UserKind.JOB_SEEKER, is_active=True)

        objects_to_save = list(geolocate_qs(qs, is_verbose=True, reliance_score=reliance_score))
        if wet_run:
            qs.model.objects.bulk_update(
                objects_to_save,
                ["coords", "geocoding_score", "ban_api_resolved_address", "geocoding_updated_at"],
            )
            self.stdout.write(f"> count={len(objects_to_save)} {mode} geolocated with a high score.")
