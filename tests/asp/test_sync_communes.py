from django.core import management

from itou.asp.models import Commune
from itou.cities.models import City


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

    assert Commune.objects.current().filter(city=None).count() == 19

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
