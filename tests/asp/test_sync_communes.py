import datetime

from django.core import management

from itou.asp.models import Commune
from itou.cities.models import City
from tests.users.factories import JobSeekerFactory


def test_sync_commune(snapshot, capsys):
    management.call_command(
        "sync_communes",
        file_path="tests/asp/fake_ref_insee_com_v1.csv",
        wet_run=True,
    )
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == snapshot(name="original_communes")

    assert Commune.objects.current().filter(city=None).count() == 20

    billy_v1 = Commune.objects.get(code="41016", name="BILLY")

    assert billy_v1.start_date == datetime.date(1900, 1, 1)

    js = JobSeekerFactory(jobseeker_profile__birthdate=datetime.date(1990, 1, 1))
    js.jobseeker_profile.hexa_commune = billy_v1
    js.jobseeker_profile.birth_place = billy_v1
    js.jobseeker_profile.save()

    City.objects.create(
        name="Houdain",
        code_insee="62457",
        slug="houdain-62",
        department="62",
        coords="POINT(2.4733 50.4858)",
        post_codes=["62150"],
    )

    management.call_command(
        "sync_communes",
        file_path="tests/asp/fake_ref_insee_com_v1.csv",
        wet_run=True,
    )
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == snapshot(name="with_cities")

    assert Commune.objects.current().filter(city=None).count() == 20

    # get a commune that is named "CRANS" to check later that the name is changed
    crans = Commune.objects.get(code="01129", name="CRANS")

    management.call_command(
        "sync_communes",
        file_path="tests/asp/fake_ref_insee_com_v2.csv",
        wet_run=True,
    )
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == snapshot(name="modified_communes")

    crans.refresh_from_db()
    assert crans.name == "CRANS-LENNUI"

    # Verify that the commune "BILLY" whose start date has changed from 1900 to 1942 has been remapped
    js.jobseeker_profile.refresh_from_db()
    assert js.jobseeker_profile.hexa_commune.start_date == datetime.date(1942, 1, 1)
    assert js.jobseeker_profile.birth_place.start_date == datetime.date(1942, 1, 1)
