import datetime

from django import db
from django.db import transaction
from django.forms import models
from django.utils import timezone

from itou.analytics import api_usage, approvals, employee_record, tech, users
from itou.analytics.models import Datum
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--save", action="store_true", default=False, help="Save the data into the database")
        parser.add_argument("--offset", type=int, default=0, help="Offset the cutoff date by that number of days")

    def handle(self, *args, **options):
        before = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(
            days=options["offset"]
        )
        self.logger.info(f"Collecting analytics data before '{before!s}'.")

        data = self._get_data(before)
        self.logger.info("Analytics data computed.")

        self.show_data(data)
        if options["save"]:
            self.save_data(data, before)

    @staticmethod
    def _get_data(before):
        return {
            **approvals.collect_analytics_data(before),
            **employee_record.collect_analytics_data(before),
            **users.collect_analytics_data(before),
            **api_usage.collect_analytics_data(before),
            **tech.collect_analytics_data(before),
        }

    def show_data(self, data):
        for code, value in data.items():
            self.logger.info(f"{code.label} ({code.value}): {value}")

    def save_data(self, data, before):
        bucket = (before.date() - datetime.timedelta(days=1)).isoformat()
        self.logger.info(f"Saving analytics data in bucket '{bucket}'.")
        for code, value in data.items():
            datum = Datum(
                code=code.value,
                bucket=bucket,
                value=value,
            )
            try:
                with transaction.atomic():
                    datum.save()
            except db.IntegrityError:
                self.logger.warning(f"Failed to save code={code.value} for bucket={bucket} because it already exists.")
            except models.ValidationError as error:
                message = (
                    f"Failed to save code={code.value} for bucket={bucket} because of a ValidationError: "
                    f"{error.message}"
                )
                self.logger.error(message)
            else:
                self.logger.info(f"Successfully saved code={code.value} bucket={bucket} value={value}.")
