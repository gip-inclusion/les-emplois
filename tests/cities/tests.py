from django.contrib.gis.geos import Point
from django.core import management
from django.core.management import call_command
from pytest_django.asserts import assertQuerySetEqual

from itou.cities.models import City, EditionModeChoices
from tests.cities.factories import create_city_guerande, create_test_cities
from tests.users.factories import JobSeekerFactory


def test_create_test_cities():
    create_test_cities(["62", "67", "93"], num_per_department=10)
    assert City.objects.count() == 30
    assert City.objects.filter(department="62").count() == 10
    assert City.objects.filter(department="67").count() == 10
    assert City.objects.filter(department="93").count() == 10


def test_sync_cities(settings, capsys, respx_mock):
    settings.API_GEO_BASE_URL = "https://geo.foo"
    respx_mock.get(
        "https://geo.foo/communes?fields=nom,code,codesPostaux,codeDepartement,codeRegion,centre&format=json"
    ).respond(
        200,
        json=[
            {
                "centre": {"coordinates": [4.9306, 46.1517], "type": "Point"},
                "code": "01001",
                "codeDepartement": "01",
                "codeRegion": "84",
                "codesPostaux": ["01400", "01234"],
                "nom": "L'Abergement-Clémenciat",
            },
            {
                "centre": {"coordinates": [5.4247, 46.0071], "type": "Point"},
                "code": "01002",
                "codeDepartement": "01",
                "codeRegion": "84",
                "codesPostaux": ["01640"],
                "nom": "L'Abergement-de-Varey",
            },
        ],
    )
    respx_mock.get(
        "https://geo.foo/communes?fields=nom,code,codesPostaux,codeDepartement,codeRegion,centre"
        "&format=json&type=arrondissement-municipal"
    ).respond(
        200,
        json=[
            {
                "centre": {"coordinates": [5.3828, 43.3002], "type": "Point"},
                "code": "13201",
                "codeDepartement": "13",
                "codeRegion": "93",
                "codesPostaux": ["13001"],
                "nom": "Marseille 1er Arrondissement",
            },
            {
                "centre": {"coordinates": [5.3496, 43.3225], "type": "Point"},
                "code": "13202",
                "codeDepartement": "13",
                "codeRegion": "93",
                "codesPostaux": ["13002"],
                "nom": "Marseille 2e Arrondissement",
            },
        ],
    )

    create_city_guerande()  # will be removed

    # will modify, since it's the same INSEE code
    City.objects.create(
        code_insee="01001",
        name="Nouveau Nom de Ville",
        slug="nouvelle-ville-01",
        department="01",
        coords=Point(-2.4747713, 47.3358576),
        post_codes=["01234"],
    )

    # workaround the forced save() that sets MANUAL mode up
    City.objects.update(edition_mode=EditionModeChoices.AUTO)

    management.call_command("sync_cities", wet_run=True)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "count=1 label=City had the same key in collection and queryset",
        "\tCHANGED name=Nouveau Nom de Ville changed to value=L'Abergement-Clémenciat",
        "\tCHANGED post_codes=['01234'] changed to value=['01234', '01400']",
        "\tCHANGED coords=SRID=4326;POINT (-2.4747713 47.3358576) changed to "
        "value=SRID=4326;POINT (4.9306 46.1517)",
        "count=3 label=City added by collection",
        '\tADDED {"centre": {"coordinates": [5.4247, 46.0071], "type": "Point"}, '
        '"code": "01002", "codeDepartement": "01", "codeRegion": "84", '
        '"codesPostaux": ["01640"], "nom": "L\'Abergement-de-Varey"}',
        '\tADDED {"centre": {"coordinates": [5.3828, 43.3002], "type": "Point"}, '
        '"code": "13201", "codeDepartement": "13", "codeRegion": "93", '
        '"codesPostaux": ["13001"], "nom": "Marseille 1er"}',
        '\tADDED {"centre": {"coordinates": [5.3496, 43.3225], "type": "Point"}, '
        '"code": "13202", "codeDepartement": "13", "codeRegion": "93", '
        '"codesPostaux": ["13002"], "nom": "Marseille 2e"}',
        "count=1 label=City removed by collection",
        "\tREMOVED Guérande (44)",
        "> successfully deleted count=1 cities insee_codes={'44350'}",
        "> successfully created count=3 new cities",
        "> successfully updated count=1 cities",
    ]

    # Introduce a "bogus" item in the regular (non arrondissement) cities:
    # - "new" city in respect to its non-registered INSEE code yet
    # - even though the slug is already registered in our DB
    # Check that it does not crash; this demonstrates an "INSEE code change".
    respx_mock.get(
        "https://geo.foo/communes?fields=nom,code,codesPostaux,codeDepartement,codeRegion,centre&format=json"
    ).respond(
        200,
        json=[
            {
                "centre": {"coordinates": [4.9306, 46.1517], "type": "Point"},
                "code": "01001",
                "codeDepartement": "01",
                "codeRegion": "84",
                "codesPostaux": ["01234", "01400"],  # changing the post codes order should not change
                "nom": "L'Abergement-Clémenciat",
            },
            {
                "centre": {"coordinates": [4.9306, 46.1517], "type": "Point"},
                "code": "01003",  # same new INSEE code
                "codeDepartement": "01",
                "codeRegion": "84",
                "codesPostaux": ["01400"],
                "nom": "L'Abergement-de-Varey",
            },
        ],
    )

    # Introduce a change in one of the arrondissements: the change is now permanent
    # and any new automatic sync update to it will be skipped.
    marseille_1er = City.objects.get(slug="marseille-1er-13")
    marseille_1er.name = "Marssssssssseillle bébé"
    marseille_1er.save()

    management.call_command("sync_cities", wet_run=True)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "count=3 label=City had the same key in collection and queryset",
        "! skipping manually edited city=Marssssssssseillle bébé (13) from update",
        "count=1 label=City added by collection",
        '\tADDED {"centre": {"coordinates": [4.9306, 46.1517], "type": "Point"}, '
        '"code": "01003", "codeDepartement": "01", "codeRegion": "84", '
        '"codesPostaux": ["01400"], "nom": "L\'Abergement-de-Varey"}',
        "count=1 label=City removed by collection",
        "\tREMOVED L'Abergement-de-Varey (01)",
        "> successfully deleted count=1 cities insee_codes={'01002'}",
        "> successfully created count=1 new cities",
        "> successfully updated count=0 cities",  # no update to post codes
    ]

    assertQuerySetEqual(
        City.objects.all().order_by("code_insee"),
        [
            (
                "L'Abergement-Clémenciat",
                "labergement-clemenciat-01",
                "01",
                ["01234", "01400"],
                "01001",
                "SRID=4326;POINT (4.9306 46.1517)",
                "AUTO",
            ),
            (
                "L'Abergement-de-Varey",
                "labergement-de-varey-01",
                "01",
                ["01400"],
                "01003",
                "SRID=4326;POINT (4.9306 46.1517)",
                "AUTO",
            ),
            (
                "Marssssssssseillle bébé",
                "marseille-1er-13",
                "13",
                ["13001"],
                "13201",
                "SRID=4326;POINT (5.3828 43.3002)",
                "MANUAL",
            ),
            (
                "Marseille 2e",
                "marseille-2e-13",
                "13",
                ["13002"],
                "13202",
                "SRID=4326;POINT (5.3496 43.3225)",
                "AUTO",
            ),
        ],
        transform=lambda city: (
            city.name,
            city.slug,
            city.department,
            city.post_codes,
            city.code_insee,
            city.coords,
            city.edition_mode,
        ),
    )


def test_resolve_insee_cities(capsys, snapshot):
    guerande = create_city_guerande()  # Guérande, 44350
    user = JobSeekerFactory(city="GUERAND", post_code="44350", geocoding_score=0.9)
    non_resolved_user_1 = JobSeekerFactory(city="Guérande", post_code="54350", geocoding_score=0.9)
    non_resolved_user_2 = JobSeekerFactory(city="ERAND", post_code="44350", geocoding_score=0.9)
    call_command("resolve_insee_cities", wet_run=True, mode="job_seekers")
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == snapshot(name="first_pass")

    user.refresh_from_db()
    assert user.insee_city == guerande
    non_resolved_user_1.refresh_from_db()
    non_resolved_user_1.geocoding_score = 0.0
    non_resolved_user_2.refresh_from_db()
    non_resolved_user_2.geocoding_score = 0.0

    # no users selected: they either have a city or a low geocoding score.
    call_command("resolve_insee_cities", wet_run=True, mode="job_seekers")
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == snapshot(name="second_pass")
