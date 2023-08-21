import csv
import os
import os.path
from io import StringIO

import respx
from django.conf import settings
from django.core import management
from django.test import override_settings
from httpx import Response

from tests.users.factories import JobSeekerWithAddressFactory
from tests.utils.test import TestCase


def mock_ban_api(user_id):
    resp = Response(
        200,
        text=f"""id;adresse_line_1;post_code;city;result_label;result_score;latitude;longitude\n"""
        f"""{user_id};10 rue du Moulin du Gue;35400;Saint-Malo;"""
        f"""10 Rue du Moulin du Gue 35400 Saint-Malo;0.97;48.658983;-1.963752\r\n""",
    )
    respx.post(settings.API_BAN_BASE_URL + "/search/csv").mock(return_value=resp)


@override_settings(API_BAN_BASE_URL="https://foobar.com")
class GeolocateJobseekerManagementCommandTest(TestCase):
    """
    Bulk update - import - export of user location via BAN API.
    Was in the `geo` app, but is likely to be "one-shot", hence moved to `scripts`.
    """

    def run_command(self, *args, **kwargs):
        out = StringIO()
        err = StringIO()

        management.call_command("geolocate_jobseeker_addresses", *args, stdout=out, stderr=err, **kwargs)

        return out.getvalue(), err.getvalue()

    def test_update_dry_run(self):
        JobSeekerWithAddressFactory(is_active=True, without_geoloc=True)

        out, _ = self.run_command("update")

        assert "Geolocation of active job seekers addresses (updating DB)" in out
        assert "+ NOT storing data" in out
        assert "+ NOT calling geo API" in out

    @respx.mock
    def test_update_wet_run(self):
        user = JobSeekerWithAddressFactory(
            is_active=True,
            without_geoloc=True,
            address_line_1="10 rue du Moulin du Gue",
            post_code="35400",
            city="Saint-Malo",
        )

        mock_ban_api(user.pk)

        out, _ = self.run_command("update", wet_run=True)

        assert "Geolocation of active job seekers addresses (updating DB)" in out
        assert "+ NOT storing data" not in out
        assert "+ NOT calling geo API" not in out

        user.refresh_from_db()

        assert "SRID=4326;POINT (-1.963752 48.658983)" == user.coords
        assert 0.97 == user.geocoding_score
        assert "+ updated: 1, errors: 0, total: 1" in out

    def test_export_dry_run(self):
        out, _ = self.run_command("export")

        assert "Export job seeker geocoding data to file:" in out
        assert "+ implicit 'dry-run': NOT creating file" in out

    def test_export_wet_run(self):
        coords = "SRID=4326;POINT (-1.963752 48.658983)"
        score = 0.97
        JobSeekerWithAddressFactory(
            is_active=True,
            coords=coords,
            geocoding_score=score,
        )
        path = os.path.join(settings.EXPORT_DIR, "export.csv")

        out, _ = self.run_command("export", filename=path, wet_run=True)

        assert "+ found 1 geocoding entries with score > 0.0" in out

        # Could not find an elegant way to mock file creation
        # `mock_open()` does not seem to be the right thing to use for write ops
        # Works well for reading ops though
        with open(path) as f:
            [_, row] = csv.reader(f, delimiter=";")
            assert coords in row
            assert str(score) in row

    def test_import_dry_run(self):
        out, _ = self.run_command("import", filename="foo")

        assert "Import job seeker geocoding data from file:" in out
        assert "+ implicit `dry-run`: reading file but NOT writing into DB" in out

    def test_import_wet_run(self):
        user = JobSeekerWithAddressFactory(is_active=True)
        path = os.path.join(settings.IMPORT_DIR, "sample_user_geoloc.csv")

        with open(path, "w") as f:
            f.write("id;coords;geocoding_score\n")
            f.write(f"""{user.pk};"SRID=4326;POINT (-1.963752 48.658983)";0.97""")

        out, _ = self.run_command("import", filename=path, wet_run=True)

        assert "Import job seeker geocoding data from file:" in out

        user.refresh_from_db()

        assert 0.97 == user.geocoding_score
        assert "SRID=4326;POINT (-1.963752 48.658983)" == user.coords
        assert "+ updated 1 'user.User' objects" in out
