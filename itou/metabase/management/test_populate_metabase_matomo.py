import time

import pytest
import tenacity
from django.core import management
from django.db import connection
from django.test import override_settings
from freezegun import freeze_time


MATOMO_HEADERS = (
    "Unique visitors,Visits,Users,Actions,Maximum actions in one visit,Bounces,"
    "Total time spent by visitors (in seconds),New Visits,Actions by New Visits,"
    "Unique new visitors,New Users,max_actions_new,Bounce Rate for New Visits,"
    "Avg. Actions per New Visit,Avg. Duration of a New Visit (in sec),"
    "Returning Visits,Actions by Returning Visits,Unique returning visitors,"
    "Returning Users,Maximum actions in one returning visit,Bounce Rate for Returning Visits,"
    "Avg. Actions per Returning Visit,Avg. Duration of a Returning Visit (in sec),"
    "Visitors from Search Engines,Visitors from Social Networks,Visitors from Direct Entry,"
    "Visitors from Websites,Visitors from Campaigns,Distinct search engines,Distinct social networks,"
    "Distinct keywords,Distinct websites,Referrers_distinctWebsitesUrls,Distinct campaigns,"
    "Percent of Visitors from Direct Entry,Percent of Visitors from Search Engines,"
    "Percent of Visitors from Campaigns,Percent of Visitors from Social Networks,"
    "Percent of Visitors from Websites,PagePerformance_network_time,PagePerformance_network_hits,"
    "PagePerformance_servery_time,PagePerformance_server_hits,PagePerformance_transfer_time,"
    "PagePerformance_transfer_hits,PagePerformance_domprocessing_time,PagePerformance_domprocessing_hits,"
    "PagePerformance_domcompletion_time,PagePerformance_domcompletion_hits,PagePerformance_onload_time,"
    "PagePerformance_onload_hits,PagePerformance_pageload_time,PagePerformance_pageload_hits,"
    "Avg. network time,Avg. server time,Avg. transfer time,Avg. DOM processing time,"
    "Avg. DOM completion time,Avg. on load time,Avg. page load time,Conversions,Visits with Conversions,"
    "Revenue,Conversion Rate,nb_conversions_new_visit,nb_visits_converted_new_visit,revenue_new_visit,"
    "conversion_rate_new_visit,nb_conversions_returning_visit,nb_visits_converted_returning_visit,"
    "revenue_returning_visit,conversion_rate_returning_visit,Pageviews,Unique Pageviews,Downloads,"
    "Unique Downloads,Outlinks,Unique Outlinks,Searches,Unique Keywords,Bounce Rate,Actions per Visit,"
    "Avg. Visit Duration (in seconds)"
)

MATOMO_ONLINE_CONTENT = (
    "25,26,0,242,43,1,17222,13,132,13,0,43,0%,10.2,12 min 36s,13,110,13,0,24,8%,8.5,9 min 29s,0,0,"
    "17,9,0,0,0,0,2,4,0,65%,0%,0%,0%,35%,27.411,225,111.02,225,7.119,224,149.254,167,178.406,123,"
    "1.025,123,474.235,225,0.12s,0.49s,0.03s,0.89s,1.45s,0.01s,2.11s,0,0,0,0%,0,0,0,0%,0,0,0,0%,"
    "225,95,0,0,17,12,0,0,4%,9.3,11 min 2s"
)


@override_settings(MATOMO_BASE_URL="https://mato.mo", MATOMO_AUTH_TOKEN="foobar")
@pytest.mark.django_db(transaction=True)
@pytest.mark.respx(base_url="https://mato.mo")
@pytest.mark.usefixtures("metabase")
@freeze_time("2022-06-21")
def test_matomo_retry(monkeypatch, respx_mock, capsys):
    monkeypatch.setattr(time, "sleep", lambda x: None)
    respx_mock.get("/index.php").respond(
        500,
        content=f"{MATOMO_HEADERS}\n{MATOMO_ONLINE_CONTENT}".encode("utf-16"),
    )
    with pytest.raises(tenacity.RetryError):
        management.call_command("populate_metabase_matomo", wet_run=True, mode="public")
    stdout, _ = capsys.readouterr()
    # sort the output because it's random (ThreadPoolExecutor)
    assert [line[:70] for line in sorted(stdout.splitlines())] == [
        "\t> fetching date=2022-06-13 dashboard='tb 116 - Recrutement' pageUrl=h",
        "\t> fetching date=2022-06-13 dashboard='tb 129 - Analyse des publics' p",
        "\t> fetching date=2022-06-13 dashboard='tb 136 - Prescripteurs habilité",
        "\t> fetching date=2022-06-13 dashboard='tb 140 - ETP conventionnés' pag",
        "\t> fetching date=2022-06-13 dashboard='tb 150 - Fiches de poste en ten",
        "\t> fetching date=2022-06-13 dashboard='tb 216 - Les femmes dans l'IAE'",
        "\t> fetching date=2022-06-13 dashboard='tb 217 - Suivi pass IAE' pageUr",
        "\t> fetching date=2022-06-13 dashboard='tb 218 - Cartographie de l'IAE'",
        "\t> fetching date=2022-06-13 dashboard='tb 32 - Acceptés en auto-prescr",
        "\t> fetching date=2022-06-13 dashboard='tb 43 - Statistiques des emploi",
        "\t> fetching date=2022-06-13 dashboard='tb 52 - Typologie de prescripte",
        "\t> fetching date=2022-06-13 dashboard='tb 54 - Typologie des employeur",
        "\t> fetching date=2022-06-13 dashboard='tb 90 - Analyse des métiers' pa",
        "> about to fetch count=13 public dashboards from Matomo.",
    ] + ["For more information check: https://httpstatuses.com/500"] * 39 + [
        "attempt=1 failed with outcome=Server error '500 Internal Server Error'"
    ] * 13 + [
        "attempt=2 failed with outcome=Server error '500 Internal Server Error'"
    ] * 13 + [
        "attempt=3 failed with outcome=Server error '500 Internal Server Error'"
    ] * 13


@override_settings(MATOMO_BASE_URL="https://mato.mo", MATOMO_AUTH_TOKEN="foobar")
@pytest.mark.django_db(transaction=True)
@pytest.mark.respx(base_url="https://mato.mo")
@pytest.mark.usefixtures("metabase")
@freeze_time("2022-06-21")
def test_matomo_populate_public(monkeypatch, respx_mock):
    monkeypatch.setattr(time, "sleep", lambda x: None)
    respx_mock.get("/index.php").respond(
        200,
        content=f"{MATOMO_HEADERS}\n{MATOMO_ONLINE_CONTENT}".encode("utf-16"),
    )
    management.call_command("populate_metabase_matomo", wet_run=True, mode="public")
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM suivi_visiteurs_tb_publics_v0")
        rows = cursor.fetchall()
        assert len(rows) == 13
        assert rows[0] == (
            "25",
            "26",
            "0",
            "242",
            "43",
            "1",
            "17222",
            "13",
            "132",
            "13",
            "0",
            "43",
            "0%",
            "10.2",
            "12 min 36s",
            "13",
            "110",
            "13",
            "0",
            "24",
            "8%",
            "8.5",
            "9 min 29s",
            "0",
            "0",
            "17",
            "9",
            "0",
            "0",
            "0",
            "0",
            "2",
            "4",
            "0",
            "65%",
            "0%",
            "0%",
            "0%",
            "35%",
            "27.411",
            "225",
            "111.02",
            "225",
            "7.119",
            "224",
            "149.254",
            "167",
            "178.406",
            "123",
            "1.025",
            "123",
            "474.235",
            "225",
            "0.12s",
            "0.49s",
            "0.03s",
            "0.89s",
            "1.45s",
            "0.01s",
            "2.11s",
            "0",
            "0",
            "0",
            "0%",
            "0",
            "0",
            "0",
            "0%",
            "0",
            "0",
            "0",
            "0%",
            "225",
            "95",
            "0",
            "0",
            "17",
            "12",
            "0",
            "0",
            "4%",
            "9.3",
            "11 min 2s",
            "2022-06-13",
            "tb 116 - Recrutement",
        )


@override_settings(MATOMO_BASE_URL="https://mato.mo")
@pytest.mark.django_db(transaction=True)
@pytest.mark.respx(base_url="https://mato.mo")
@pytest.mark.usefixtures("metabase")
@freeze_time("2022-06-21")
def test_matomo_populate_private(monkeypatch, respx_mock):

    # lazy import, if we import at the root the metabase fixture won't work.
    from .commands import populate_metabase_matomo

    # rewrite the REGIONS import or the test, even with mocked HTTP calls, is several minutes
    monkeypatch.setattr(populate_metabase_matomo, "REGIONS", {"Bretagne": ["75", "31"]})
    monkeypatch.setattr(time, "sleep", lambda x: None)
    respx_mock.get("/index.php").respond(
        200,
        content=f"{MATOMO_HEADERS}\n{MATOMO_ONLINE_CONTENT}".encode("utf-16"),
    )
    management.call_command("populate_metabase_matomo", wet_run=True, mode="private")
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM suivi_visiteurs_tb_prives_v0")
        rows = cursor.fetchall()
        assert len(rows) == 23
        assert rows[0] == (
            "25",
            "26",
            "0",
            "242",
            "43",
            "1",
            "17222",
            "13",
            "132",
            "13",
            "0",
            "43",
            "0%",
            "10.2",
            "12 min 36s",
            "13",
            "110",
            "13",
            "0",
            "24",
            "8%",
            "8.5",
            "9 min 29s",
            "0",
            "0",
            "17",
            "9",
            "0",
            "0",
            "0",
            "0",
            "2",
            "4",
            "0",
            "65%",
            "0%",
            "0%",
            "0%",
            "35%",
            "27.411",
            "225",
            "111.02",
            "225",
            "7.119",
            "224",
            "149.254",
            "167",
            "178.406",
            "123",
            "1.025",
            "123",
            "474.235",
            "225",
            "0.12s",
            "0.49s",
            "0.03s",
            "0.89s",
            "1.45s",
            "0.01s",
            "2.11s",
            "0",
            "0",
            "0",
            "0%",
            "0",
            "0",
            "0",
            "0%",
            "0",
            "0",
            "0",
            "0%",
            "225",
            "95",
            "0",
            "0",
            "17",
            "12",
            "0",
            "0",
            "4%",
            "9.3",
            "11 min 2s",
            "2022-06-13",
            "TB DGEFP",
            None,
            None,
            None,
        )
        assert [line[-5:] for line in rows] == [
            ("2022-06-13", "TB DGEFP", None, None, None),
            ("2022-06-13", "tb 117 - Données IAE DREETS/DDETS", None, None, "Bretagne"),
            ("2022-06-13", "tb 149 - Candidatures orientées PE", None, None, "Bretagne"),
            ("2022-06-13", "tb 160 - Facilitation de l'embauche DREETS/DDETS", None, None, "Bretagne"),
            ("2022-06-13", "tb 162 - Fiches de poste en tension PE", None, None, "Bretagne"),
            ("2022-06-13", "tb 168 - Délai d'entrée en IAE", None, None, "Bretagne"),
            ("2022-06-13", "tb 169 - Taux de transformation PE", None, None, "Bretagne"),
            ("2022-06-13", "tb 117 - Données IAE DREETS/DDETS", "31 - Haute-Garonne", "31", "Occitanie"),
            ("2022-06-13", "tb 118 - Données IAE CD", "31 - Haute-Garonne", "31", "Occitanie"),
            ("2022-06-13", "tb 149 - Candidatures orientées PE", "31 - Haute-Garonne", "31", "Occitanie"),
            (
                "2022-06-13",
                "tb 160 - Facilitation de l'embauche DREETS/DDETS",
                "31 - Haute-Garonne",
                "31",
                "Occitanie",
            ),
            ("2022-06-13", "tb 162 - Fiches de poste en tension PE", "31 - Haute-Garonne", "31", "Occitanie"),
            ("2022-06-13", "tb 165 - Recrutement SIAE", "31 - Haute-Garonne", "31", "Occitanie"),
            ("2022-06-13", "tb 168 - Délai d'entrée en IAE", "31 - Haute-Garonne", "31", "Occitanie"),
            ("2022-06-13", "tb 169 - Taux de transformation PE", "31 - Haute-Garonne", "31", "Occitanie"),
            ("2022-06-13", "tb 117 - Données IAE DREETS/DDETS", "75 - Paris", "75", "Île-de-France"),
            ("2022-06-13", "tb 118 - Données IAE CD", "75 - Paris", "75", "Île-de-France"),
            ("2022-06-13", "tb 149 - Candidatures orientées PE", "75 - Paris", "75", "Île-de-France"),
            ("2022-06-13", "tb 160 - Facilitation de l'embauche DREETS/DDETS", "75 - Paris", "75", "Île-de-France"),
            ("2022-06-13", "tb 162 - Fiches de poste en tension PE", "75 - Paris", "75", "Île-de-France"),
            ("2022-06-13", "tb 165 - Recrutement SIAE", "75 - Paris", "75", "Île-de-France"),
            ("2022-06-13", "tb 168 - Délai d'entrée en IAE", "75 - Paris", "75", "Île-de-France"),
            ("2022-06-13", "tb 169 - Taux de transformation PE", "75 - Paris", "75", "Île-de-France"),
        ]


@override_settings(MATOMO_BASE_URL="https://mato.mo", MATOMO_AUTH_TOKEN="foobar")
@pytest.mark.django_db(transaction=True)
@pytest.mark.respx(base_url="https://mato.mo")
@pytest.mark.usefixtures("metabase")
@freeze_time("2022-06-21")
def test_matomo_empty_output(monkeypatch, respx_mock, capsys):
    monkeypatch.setattr(time, "sleep", lambda x: None)
    MATOMO_ONLINE_EMPTY_CONTENT = "0," * 56 + "0"
    respx_mock.get("/index.php").respond(
        200,
        content=f"{MATOMO_HEADERS}\n{MATOMO_ONLINE_EMPTY_CONTENT}".encode("utf-16"),
    )
    management.call_command("populate_metabase_matomo", wet_run=True, mode="public")
    stdout, _ = capsys.readouterr()
    # sort the output because it's random (ThreadPoolExecutor)
    assert sorted(stdout.splitlines()) == [
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 116 - Recrutement",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 129 - Analyse des " "publics",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 136 - Prescripteurs " "habilités",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 140 - ETP " "conventionnés",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 150 - Fiches de " "poste en tension",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 216 - Les femmes dans " "l'IAE",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 217 - Suivi pass " "IAE",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 218 - Cartographie de " "l'IAE",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 32 - Acceptés en " "auto-prescription",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 43 - Statistiques " "des emplois",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 52 - Typologie de " "prescripteurs",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 54 - Typologie des " "employeurs",
        "\t! empty matomo values for date=2022-06-13 dashboard=tb 90 - Analyse des " "métiers",
        "\t> fetching date=2022-06-13 dashboard='tb 116 - Recrutement' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/etat-suivi-candidatures/",
        "\t> fetching date=2022-06-13 dashboard='tb 129 - Analyse des publics' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/analyse-des-publics/",
        "\t> fetching date=2022-06-13 dashboard='tb 136 - Prescripteurs habilités' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/prescripteurs-habilites/",
        "\t> fetching date=2022-06-13 dashboard='tb 140 - ETP conventionnés' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/etp-conventionnes/",
        "\t> fetching date=2022-06-13 dashboard='tb 150 - Fiches de poste en tension' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/postes-en-tension/",
        "\t> fetching date=2022-06-13 dashboard='tb 216 - Les femmes dans l'IAE' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/femmes-iae/",
        "\t> fetching date=2022-06-13 dashboard='tb 217 - Suivi pass IAE' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/suivi-pass-iae/",
        "\t> fetching date=2022-06-13 dashboard='tb 218 - Cartographie de l'IAE' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/cartographies-iae/",
        "\t> fetching date=2022-06-13 dashboard='tb 32 - Acceptés en "
        "auto-prescription' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/auto-prescription/",
        "\t> fetching date=2022-06-13 dashboard='tb 43 - Statistiques des emplois' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/statistiques-emplois/",
        "\t> fetching date=2022-06-13 dashboard='tb 52 - Typologie de prescripteurs' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/zoom-prescripteurs/",
        "\t> fetching date=2022-06-13 dashboard='tb 54 - Typologie des employeurs' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/zoom-employeurs/",
        "\t> fetching date=2022-06-13 dashboard='tb 90 - Analyse des métiers' "
        "pageUrl=https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/metiers/",
        "> about to fetch count=13 public dashboards from Matomo.",
    ]
