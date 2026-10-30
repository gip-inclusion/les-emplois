import datetime
import re
from textwrap import dedent

import pytest
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

    js = JobSeekerFactory(
        born_in_france=True,
        jobseeker_profile__birth_place=billy_v1,
        jobseeker_profile__birthdate=datetime.date(1990, 1, 1),
        jobseeker_profile__hexa_commune=billy_v1,
    )

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
    assert re.sub(r"item\.db_obj\.pk=\d+", "item.db_obj.pk=[City PK]", stdout).splitlines() == snapshot(
        name="modified_communes"
    )

    crans.refresh_from_db()
    assert crans.name == "CRANS-LENNUI"

    # Verify that the commune "BILLY" whose start date has changed from 1900 to 1942 has been remapped
    js.jobseeker_profile.refresh_from_db()
    assert js.jobseeker_profile.hexa_commune.start_date == datetime.date(1942, 1, 1)
    assert js.jobseeker_profile.birth_place.start_date == datetime.date(1942, 1, 1)


def test_inconsistent_dates(capsys, tmp_path):
    inconsistent_csv = tmp_path / "data.csv"
    inconsistent_csv.write_text(
        dedent("""\
        code_com_insee;lib_com;date_deb_insee;date_fin_insee
        28238;MARVILLE-LES-BOIS;20/12/1972;19/12/1972
        38063;BURCIN;01/01/2000;
        65323;MONTSERIE;01/01/2000;
        65323;MONTSERIE;01/01/1900;31/12/1999
        65323;MONTSERIE;01/01/2000;31/12/2006
    """)
    )

    with pytest.raises(RuntimeError, match="Inconsistent data in csv"):
        management.call_command(
            "sync_communes",
            file_path=inconsistent_csv,
            wet_run=True,
        )
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "Impossible dates for 28238:",
        "- [1972-12-20, 1972-12-19]: MARVILLE-LES-BOIS",
        "Overlapping dates for 65323:",
        "- [1900-01-01, 1999-12-31]: MONTSERIE",
        "- [2000-01-01, NULL): MONTSERIE",
        "- [2000-01-01, 2006-12-31]: MONTSERIE",
    ]


def test_ignore_communes(tmp_path):
    # Some communes have been flagged as ignored to avoid issues with the ASP
    # Cf commits 731a8686d & f6296a959
    ignored_communes_csv = tmp_path / "data.csv"
    ignored_communes_csv.write_text(
        dedent("""\
        code_com_insee;lib_com;date_deb_insee;date_fin_insee
        98501;ACOUA;01/01/1900;30/03/2011
    """)
    )
    management.call_command(
        "sync_communes",
        file_path=ignored_communes_csv,
        wet_run=True,
    )
    acoua = Commune.objects.get(code="98501")
    acoua.ignore = True
    acoua.save()
    management.call_command(
        "sync_communes",
        file_path=ignored_communes_csv,
        wet_run=True,
    )
    acoua = Commune.unfiltered_objects.get(pk=acoua.pk)
    assert acoua.ignore
