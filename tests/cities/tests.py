from django.contrib.gis.geos import Point
from django.core import management
from django.core.management import call_command
from pytest_django.asserts import assertQuerySetEqual

from itou.cities.management.commands.sync_cities import get_next_insee_code
from itou.cities.models import City, EditionModeChoices
from tests.cities.factories import create_city_guerande, create_test_cities
from tests.companies.factories import JobDescriptionFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import JobSeekerFactory


def test_create_test_cities():
    create_test_cities(["62", "67", "93"], num_per_department=10)
    assert City.objects.count() == 30
    assert City.objects.filter(department="62").count() == 10
    assert City.objects.filter(department="67").count() == 10
    assert City.objects.filter(department="93").count() == 10


def test_sync_cities(settings, caplog, respx_mock):
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
    assert caplog.messages[:-1] == [
        (
            "HTTP Request: GET https://geo.foo/communes"
            '?fields=nom%2Ccode%2CcodesPostaux%2CcodeDepartement%2CcodeRegion%2Ccentre&format=json "HTTP/1.1 200 OK"'
        ),
        (
            "HTTP Request: GET https://geo.foo/communes?fields="
            "nom%2Ccode%2CcodesPostaux%2CcodeDepartement%2CcodeRegion%2Ccentre&format=json"
            '&type=arrondissement-municipal "HTTP/1.1 200 OK"'
        ),
        "count=1 label=City had the same key in collection and queryset",
        "\tCHANGED name=Nouveau Nom de Ville changed to value=L'Abergement-Clémenciat",
        "\tCHANGED post_codes=['01234'] changed to value=['01234', '01400']",
        "\tCHANGED coords=SRID=4326;POINT (-2.4747713 47.3358576) changed to value=SRID=4326;POINT (4.9306 46.1517)",
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
        "Removed location from count=0 JobDescription due to city deletion",
        "Removed insee_city from count=0 Company due to city deletion",
        "Removed insee_city from count=0 PrescriberOrganization due to city deletion",
        "Removed insee_city from count=0 User due to city deletion",
        "Removed insee_city from count=0 Institution due to city deletion",
        "successfully deleted count=1 cities insee_codes=['44350']",
        "successfully updated count=1 cities",
        "successfully created count=3 new cities",
        "count=0 cities to replace",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.cities.management.commands.sync_cities succeeded in"
    )

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
    caplog.clear()
    marseille_1er = City.objects.get(slug="marseille-1er-13")
    marseille_1er.name = "Marssssssssseillle bébé"
    marseille_1er.save()

    management.call_command("sync_cities", wet_run=True)
    assert caplog.messages[:-1] == [
        (
            "HTTP Request: GET https://geo.foo/communes"
            '?fields=nom%2Ccode%2CcodesPostaux%2CcodeDepartement%2CcodeRegion%2Ccentre&format=json "HTTP/1.1 200 OK"'
        ),
        (
            "HTTP Request: GET https://geo.foo/communes?fields="
            "nom%2Ccode%2CcodesPostaux%2CcodeDepartement%2CcodeRegion%2Ccentre&format=json"
            '&type=arrondissement-municipal "HTTP/1.1 200 OK"'
        ),
        "count=3 label=City had the same key in collection and queryset",
        "skipping manually edited city=Marssssssssseillle bébé (13) from update",
        "count=1 label=City added by collection",
        '\tADDED {"centre": {"coordinates": [4.9306, 46.1517], "type": "Point"}, '
        '"code": "01003", "codeDepartement": "01", "codeRegion": "84", '
        '"codesPostaux": ["01400"], "nom": "L\'Abergement-de-Varey"}',
        "count=1 label=City removed by collection",
        "\tREMOVED L'Abergement-de-Varey (01)",
        "Removed location from count=0 JobDescription due to city deletion",
        "Removed insee_city from count=0 Company due to city deletion",
        "Removed insee_city from count=0 PrescriberOrganization due to city deletion",
        "Removed insee_city from count=0 User due to city deletion",
        "Removed insee_city from count=0 Institution due to city deletion",
        "successfully deleted count=1 cities insee_codes=['01002']",
        "successfully updated count=0 cities",  # no update to post codes
        "successfully created count=1 new cities",
        "count=0 cities to replace",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.cities.management.commands.sync_cities succeeded in"
    )

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


def test_sync_cities_with_refill(settings, caplog, respx_mock):
    settings.API_GEO_BASE_URL = "https://geo.foo"
    settings.API_INSEE_METADATA_URL = "https://insee.foo/metadata/"

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
                "centre": {"coordinates": [5.3496, 43.3225], "type": "Point"},
                "code": "19248",
                "codeDepartement": "19",
                "codeRegion": "75",
                "codesPostaux": ["19210"],
                "nom": "Les Trois-Saints",
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
        ],
    )

    create_city_guerande()  # will be deleted - INSEE code 44350
    saint_martin_sepert = City.objects.create(
        name="Saint-Martin-Sepert",
        slug="saint-martin-sepert-19",
        department="19",
        # Dummy
        coords=Point(-2.4747713, 47.3358576),
        post_codes=["19210"],
        code_insee="19223",
    )
    # workaround the forced save() that sets MANUAL mode up
    City.objects.update(edition_mode=EditionModeChoices.AUTO)

    respx_mock.get("https://insee.foo/metadata/geo/commune/19223/suivants?date=2020-01-01").respond(
        200,
        json=[
            {
                "code": "19248",
                "uri": "http://id.insee.fr/geo/commune/4ee6ee69-c313-4110-8d62-9ac2de6cce73",
                "type": "Commune",
                "dateCreation": "2025-01-01",
                "intituleSansArticle": "Trois-Saints",
                "typeArticle": "4",
                "intitule": "Les Trois-Saints",
            }
        ],
    )
    # These objects will need to be "refilled"
    job_seeker_to_refill = JobSeekerFactory(insee_city=saint_martin_sepert)
    create_test_romes_and_appellations(["M1805"], appellations_per_rome=3)
    job_description_to_refill = JobDescriptionFactory(location=saint_martin_sepert)

    management.call_command("sync_cities", wet_run=True)
    new_city = City.objects.get(code_insee="19248")
    assert caplog.messages[:-1] == [
        (
            "HTTP Request: GET https://geo.foo/communes"
            '?fields=nom%2Ccode%2CcodesPostaux%2CcodeDepartement%2CcodeRegion%2Ccentre&format=json "HTTP/1.1 200 OK"'
        ),
        (
            "HTTP Request: GET https://geo.foo/communes?fields="
            "nom%2Ccode%2CcodesPostaux%2CcodeDepartement%2CcodeRegion%2Ccentre&format=json"
            '&type=arrondissement-municipal "HTTP/1.1 200 OK"'
        ),
        "count=0 label=City had the same key in collection and queryset",
        "count=3 label=City added by collection",
        (
            '\tADDED {"centre": {"coordinates": [4.9306, 46.1517], "type": "Point"}, '
            '"code": "01001", "codeDepartement": "01", "codeRegion": "84", '
            '"codesPostaux": ["01400", "01234"], "nom": "L\'Abergement-Clémenciat"}'
        ),
        (
            '\tADDED {"centre": {"coordinates": [5.3828, 43.3002], "type": "Point"}, '
            '"code": "13201", "codeDepartement": "13", "codeRegion": "93", '
            '"codesPostaux": ["13001"], "nom": "Marseille 1er"}'
        ),
        (
            '\tADDED {"centre": {"coordinates": [5.3496, 43.3225], "type": "Point"}, '
            '"code": "19248", "codeDepartement": "19", "codeRegion": "75", '
            '"codesPostaux": ["19210"], "nom": "Les Trois-Saints"}'
        ),
        "count=2 label=City removed by collection",
        "\tREMOVED Saint-Martin-Sepert (19)",
        "\tREMOVED Guérande (44)",
        "Removed location from count=1 JobDescription due to city deletion",
        "Removed insee_city from count=0 Company due to city deletion",
        "Removed insee_city from count=0 PrescriberOrganization due to city deletion",
        "Removed insee_city from count=1 User due to city deletion",
        "Removed insee_city from count=0 Institution due to city deletion",
        "successfully deleted count=2 cities insee_codes=['19223', '44350']",
        "successfully updated count=0 cities",  # no update to post codes
        "successfully created count=3 new cities",
        "count=1 cities to replace",
        'HTTP Request: GET https://insee.foo/metadata/geo/commune/19223/suivants?date=2020-01-01 "HTTP/1.1 200 OK"',
        "Found count=1 replacements",
        (
            f"Refilled JobDescription.location for pk={job_description_to_refill.pk} "
            f"to city={new_city.pk} (previous=19223)"
        ),
        "successfully refilled count=1 new cities for JobDescription",
        "successfully refilled count=0 new cities for Company",
        "successfully refilled count=0 new cities for PrescriberOrganization",
        f"Refilled User.insee_city for pk={job_seeker_to_refill.pk} to city={new_city.pk} (previous=19223)",
        "successfully refilled count=1 new cities for User",
        "successfully refilled count=0 new cities for Institution",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.cities.management.commands.sync_cities succeeded in"
    )
    job_seeker_to_refill.refresh_from_db()
    assert job_seeker_to_refill.insee_city.code_insee == "19248"
    job_description_to_refill.refresh_from_db()
    assert job_description_to_refill.location.code_insee == "19248"


def test_resolve_insee_cities(caplog, snapshot):
    guerande = create_city_guerande()  # Guérande, 44350
    user = JobSeekerFactory(city="GUERAND", post_code="44350", geocoding_score=0.9)
    non_resolved_user_1 = JobSeekerFactory(city="Guérande", post_code="54350", geocoding_score=0.9)
    non_resolved_user_2 = JobSeekerFactory(city="ERAND", post_code="44350", geocoding_score=0.9)
    call_command("resolve_insee_cities", wet_run=True, mode="job_seekers")
    assert caplog.messages[:-1] == snapshot(name="first_pass")
    assert caplog.messages[-1].startswith(
        "Management command itou.cities.management.commands.resolve_insee_cities succeeded in "
    )

    user.refresh_from_db()
    assert user.insee_city == guerande
    non_resolved_user_1.refresh_from_db()
    non_resolved_user_1.geocoding_score = 0.0
    non_resolved_user_2.refresh_from_db()
    non_resolved_user_2.geocoding_score = 0.0

    caplog.clear()
    # no users selected: they either have a city or a low geocoding score.
    call_command("resolve_insee_cities", wet_run=True, mode="job_seekers")
    assert caplog.messages[:-1] == snapshot(name="second_pass")
    assert caplog.messages[-1].startswith(
        "Management command itou.cities.management.commands.resolve_insee_cities succeeded in "
    )


def test_get_next_insee_code(settings, respx_mock):
    settings.API_INSEE_METADATA_URL = "https://insee.foo/metadata/"

    # Test chained calls
    respx_mock.get("https://insee.foo/metadata/geo/commune/14011/suivants?date=1944-01-01").respond(
        200,
        json=[
            {
                "code": "14011",
                "uri": "http://id.insee.fr/geo/commune/9437c71f-c249-423c-a251-70533ebcd194",
                "type": "Commune",
                "dateCreation": "1973-01-01",
                "dateSuppression": "2017-01-01",
                "intituleSansArticle": "Anctoville",
                "typeArticle": "1",
                "intitule": "Anctoville",
            }
        ],
    )
    respx_mock.get("https://insee.foo/metadata/geo/commune/14011/suivants?date=1973-01-01").respond(
        200,
        json=[
            {
                "code": "14011",
                "uri": "http://id.insee.fr/geo/commune/1a3d5580-cdac-4e01-851c-e7e6b941f499",
                "type": "Commune",
                "dateCreation": "2017-01-01",
                "dateSuppression": "2024-04-24",
                "intituleSansArticle": "Aurseulles",
                "typeArticle": "1",
                "intitule": "Aurseulles",
            }
        ],
    )
    respx_mock.get("https://insee.foo/metadata/geo/commune/14011/suivants?date=2017-01-01").respond(
        200,
        json=[
            {
                "code": "14581",
                "uri": "http://id.insee.fr/geo/commune/ddd9f1bd-2090-4346-a2a2-8f79376ab37e",
                "type": "Commune",
                "dateCreation": "2024-04-24",
                "intituleSansArticle": "Aurseulles",
                "typeArticle": "1",
                "intitule": "Aurseulles",
            }
        ],
    )
    assert get_next_insee_code("14011", date="1944-01-01") == "14581"
    assert get_next_insee_code("14011", date="1973-01-01") == "14581"
    assert get_next_insee_code("14011", date="2017-01-01") == "14581"

    # Case with 2 children:
    respx_mock.get("https://insee.foo/metadata/geo/commune/60054/suivants?date=2020-01-01").respond(
        200,
        json=[
            {
                "code": "60054",
                "uri": "http://id.insee.fr/geo/commune/b1953db5-5d8d-421a-aa36-0550242be63b",
                "type": "Commune",
                "dateCreation": "2024-01-01",
                "intituleSansArticle": "Beaumont-les-Nonains",
                "typeArticle": "0",
                "intitule": "Beaumont-les-Nonains",
            },
            {
                "code": "60694",
                "uri": "http://id.insee.fr/geo/commune/f43ab45c-1603-461e-9191-6f1824d6031b",
                "type": "Commune",
                "dateCreation": "2024-01-01",
                "intituleSansArticle": "Hauts-Talican",
                "typeArticle": "4",
                "intitule": "Les Hauts-Talican",
            },
        ],
    )
    assert get_next_insee_code("60054", date="2020-01-01") is None
