from django.core import management
from django.test import override_settings

from itou.jobs.models import Appellation, Rome


@override_settings(
    API_ESD={
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL_PARTENAIRE": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
def test_sync_rome_appellation(caplog, respx_mock, snapshot):
    respx_mock.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
        200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
    )
    respx_mock.get("https://pe.fake/offresdemploi/v2/referentiel/metiers").respond(
        200,
        json=[
            {"code": "F001", "libelle": "Pâtisserie avec accent"},
            {"code": "MET01", "libelle": "Edition"},
        ],
    )
    respx_mock.get("https://pe.fake/rome-metiers/v1/metiers/appellation?champs=code,libelle,metier(code)").respond(
        200,
        json=[
            {"code": "JOB32", "libelle": "Ecriveur de bouquins", "metier": {"code": "MET01"}},
            {"code": "papa01", "libelle": "Entraîneur sportif avéré", "metier": {"code": "B001"}},
            {"code": "papa03", "libelle": "Chef cuistor d'élite", "metier": {"code": "F002"}},
        ],
    )

    rome_0 = Rome(code="F001", name="Patisserie")
    rome_1 = Rome(code="F002", name="Arts de la table")
    rome_2 = Rome(code="B001", name="Métiers du corps")
    rome_0.save()
    rome_1.save()
    rome_2.save()
    appellation0 = Appellation(code="papa03", name="Chef cuistot d'élite", rome=rome_0)
    appellation1 = Appellation(code="papa01", name="Entraîneur sportif", rome=rome_2)
    appellation0.save()
    appellation1.save()
    management.call_command("sync_romes_and_appellations", wet_run=True)
    assert caplog.messages[:-1] == snapshot(name="logs")
    caplog.messages[-1].startswith(
        "Management command itou.jobs.management.commands.sync_romes_and_appellations succeeded in"
    )
    rome_3 = Rome(code="MET01", name="Edition")
    assert list(Rome.objects.all().order_by("code")) == [
        Rome(code="B001", name="Métiers du corps"),
        Rome(code="F001", name="Pâtisserie avec accent"),
        Rome(code="F002", name="Arts de la table"),
        rome_3,
    ]
    assert list(Appellation.objects.all().order_by("code")) == [
        Appellation(code="JOB32", name="Ecriveur de bouquins", rome=rome_3),
        Appellation(code="papa01", name="Entraîneur sportif avéré", rome=rome_2),
        Appellation(code="papa03", name="Chef cuistot d'élite", rome=rome_1),  # it got switched to rome_1
    ]
