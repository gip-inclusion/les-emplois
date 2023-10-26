import json

from django.utils import dateparse

from itou.asp import models
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def _format_date(self, date):
        return dateparse.parse_date(date) if date else date

    def _check_objects(self, model, file, file_converters):
        data_in_db = {obj.pk: obj for obj in model.objects.all()}
        with open(file) as fp:
            data_in_file = {obj["pk"]: obj for obj in json.load(fp)}

        primary_keys = set(sorted(set(data_in_db.keys()) & set(data_in_file.keys()), key=int))
        pk_with_incoherent_data = set()

        for pk in primary_keys:
            try:
                has_diff = any(
                    getattr(data_in_db[pk], field_name)
                    != file_converters.get(field_name, lambda x: x)(data_in_file[pk]["fields"][field_name])
                    for field_name in data_in_file[pk]["fields"]
                )
            except Exception as e:
                self.stdout.write(f"ERROR for pk={pk}: {e!r}")
            else:
                if has_diff:
                    self.stdout.write(
                        f"Diff for pk={pk}: "
                        + repr(
                            {
                                field_name: (
                                    getattr(data_in_db[pk], field_name),
                                    file_converters.get(field_name, lambda x: x)(
                                        data_in_file[pk]["fields"][field_name]
                                    ),
                                )
                                for field_name in data_in_file[pk]["fields"]
                            }
                        )
                    )
                    pk_with_incoherent_data.add(pk)

        self.stdout.write(f"Objects in database: {len(data_in_db)}")
        self.stdout.write(f"Objects in file: {len(data_in_file)}")
        self.stdout.write(f"PK missing from the database: {primary_keys - set(data_in_db.keys())}")
        self.stdout.write(f"PK missing from the file: {primary_keys - set(data_in_file.keys())}")
        self.stdout.write(f"PK with incoherent data: {pk_with_incoherent_data}")

    def handle(self, *args, **options):
        self.stdout.write("=== Checking INSEE communes ===")
        self._check_objects(
            models.Commune,
            "itou/asp/fixtures/asp_INSEE_communes.json",
            file_converters={"start_date": self._format_date, "end_date": self._format_date},
        )

        self.stdout.write("=== Checking INSEE departments ===")
        self._check_objects(
            models.Department,
            "itou/asp/fixtures/asp_INSEE_departments.json",
            file_converters={"start_date": self._format_date, "end_date": self._format_date},
        )

        self.stdout.write("=== Checking INSEE countries ===")
        self._check_objects(
            models.Country,
            "itou/asp/fixtures/asp_INSEE_countries.json",
            file_converters={
                "start_date": self._format_date,
                "end_date": self._format_date,
                "code": str,
                "group": str,
                "department": str,
            },
        )
