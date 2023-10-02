import datetime
import io

from django.core import management
from freezegun import freeze_time

from itou.employee_record.models import EmployeeRecord
from itou.siaes.enums import SiaeKind
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siaes import factories as siaes_factories
from tests.utils.test import TestCase


class MoveSiaeDataTest(TestCase):
    def test_uses_wet_run(self):
        siae1 = siaes_factories.SiaeWithMembershipAndJobsFactory()
        siae2 = siaes_factories.SiaeFactory()
        management.call_command("move_siae_data", from_id=siae1.pk, to_id=siae2.pk)
        assert siae1.jobs.count() == 4
        assert siae1.members.count() == 1
        assert siae2.jobs.count() == 0
        assert siae2.members.count() == 0

        management.call_command("move_siae_data", from_id=siae1.pk, to_id=siae2.pk, wet_run=True)
        assert siae1.jobs.count() == 0
        assert siae1.members.count() == 0
        assert siae2.jobs.count() == 4
        assert siae2.members.count() == 1

    def test_does_not_stop_if_kind_is_different(self):
        siae1 = siaes_factories.SiaeWithMembershipAndJobsFactory(kind=SiaeKind.ACI)
        siae2 = siaes_factories.SiaeFactory(kind=SiaeKind.EATT)
        management.call_command("move_siae_data", from_id=siae1.pk, to_id=siae2.pk, wet_run=True)
        assert siae1.jobs.count() == 0
        assert siae1.members.count() == 0
        assert siae2.jobs.count() == 4
        assert siae2.members.count() == 1

    def test_orphan_employee_records_are_cloned(self):
        old_siae, new_siae = siaes_factories.SiaeFactory.create_batch(2)
        EmployeeRecordFactory(job_application__to_siae=old_siae)

        management.call_command(
            "move_siae_data",
            from_id=old_siae.pk,
            to_id=new_siae.pk,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            wet_run=True,
        )

        assert EmployeeRecord.objects.for_siae(old_siae).count() == 0
        assert EmployeeRecord.objects.orphans().count() == 1
        assert EmployeeRecord.objects.for_siae(new_siae).count() == 1
        assert EmployeeRecord.objects.count() == 2

    def test_employee_records_are_accessible_when_the_convention_is_the_same(self):
        old_siae = siaes_factories.SiaeFactory()
        new_siae = siaes_factories.SiaeFactory(convention=old_siae.convention)
        EmployeeRecordFactory(job_application__to_siae=old_siae)

        management.call_command(
            "move_siae_data",
            from_id=old_siae.pk,
            to_id=new_siae.pk,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            wet_run=True,
        )

        assert EmployeeRecord.objects.for_siae(old_siae).count() == 0
        assert EmployeeRecord.objects.orphans().count() == 0
        assert EmployeeRecord.objects.for_siae(new_siae).count() == 1
        assert EmployeeRecord.objects.count() == 1


def test_update_siaes_job_app_score():
    siae1 = siaes_factories.SiaeFactory()
    siae2 = JobApplicationFactory(to_siae__with_jobs=True).to_siae

    assert siae1.job_app_score is None
    assert siae2.job_app_score is None

    stdout = io.StringIO()
    management.call_command("update_siaes_job_app_score", stdout=stdout)
    # siae1 did not change (from None to None)
    assert "Updated 1 Siaes" in stdout.getvalue()

    siae1.refresh_from_db()
    siae2.refresh_from_db()

    assert siae1.job_app_score is None
    assert siae2.job_app_score is not None


@freeze_time("2023-05-01")
def test_update_siae_coords(settings, capsys, respx_mock):
    siae1 = siaes_factories.SiaeFactory(coords="POINT (2.387311 48.917735)", geocoding_score=0.65)  # score too low
    siae2 = siaes_factories.SiaeFactory(coords=None, geocoding_score=0.9)  # no coords
    siae3 = siaes_factories.SiaeFactory(coords="POINT (5.43567 12.123876)", geocoding_score=0.76)  # score too low
    siaes_factories.SiaeFactory(coords="POINT (5.43567 12.123876)", geocoding_score=0.9)

    settings.API_BAN_BASE_URL = "https://geo.foo"
    respx_mock.post("https://geo.foo/search/csv/").respond(
        200,
        text=(
            "id;result_label;result_score;latitude;longitude\n"
            "42;7 rue de Laroche;0.77;42.42;13.13\n"  # score is lower than the minimum fiability score
            "12;5 rue Bigot;0.32;42.42;13.13\n"  # score is lower than the current one
            "78;9 avenue Delorme 92220 Boulogne;0.83;42.42;13.13\n"  # score is higher than current one
        ),
    )

    management.call_command("update_siae_coords", wet_run=True)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "> about to geolocate count=3 objects without geolocation or with a low " "score.",
        "> count=3 of these have an address and a post code.",
        "API result score=0.77 label='7 rue de Laroche' "
        f"searched_address='{siae1.address_line_1} {siae1.post_code}' object_pk={siae1.pk}",
        "API result score=0.32 label='5 rue Bigot' "
        f"searched_address='{siae2.address_line_1} {siae2.post_code}' object_pk={siae2.pk}",
        "API result score=0.83 label='9 avenue Delorme 92220 Boulogne' "
        f"searched_address='{siae3.address_line_1} {siae3.post_code}' object_pk={siae3.pk}",
        "> count=1 SIAEs geolocated with a high score.",
    ]

    siae3.refresh_from_db()
    assert siae3.ban_api_resolved_address == "9 avenue Delorme 92220 Boulogne"
    assert siae3.geocoding_updated_at == datetime.datetime(2023, 5, 1, 0, 0, tzinfo=datetime.UTC)
    assert siae3.geocoding_score == 0.83
    assert siae3.coords.x == 13.13
    assert siae3.coords.y == 42.42
