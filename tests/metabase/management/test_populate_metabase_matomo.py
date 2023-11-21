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
def test_matomo_retry(monkeypatch, respx_mock, capsys, snapshot):
    monkeypatch.setattr("tenacity.wait_fixed", lambda _a: None)

    respx_mock.get("/index.php").respond(
        500,
        content=f"{MATOMO_HEADERS}\n{MATOMO_ONLINE_CONTENT}".encode("utf-16"),
    )
    with pytest.raises(tenacity.RetryError):
        management.call_command("populate_metabase_matomo", wet_run=True)
    stdout, _ = capsys.readouterr()
    # sort the output because it's random (ThreadPoolExecutor)
    assert sorted(stdout.splitlines()) == snapshot(name="retry output")


@override_settings(MATOMO_BASE_URL="https://mato.mo", MATOMO_AUTH_TOKEN="foobar")
@pytest.mark.django_db(transaction=True)
@pytest.mark.respx(base_url="https://mato.mo")
@pytest.mark.usefixtures("metabase")
@freeze_time("2022-06-21")
def test_matomo_populate_public(respx_mock, snapshot):
    respx_mock.get("/index.php").respond(
        200,
        content=f"{MATOMO_HEADERS}\n{MATOMO_ONLINE_CONTENT}".encode("utf-16"),
    )
    management.call_command("populate_metabase_matomo", wet_run=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM suivi_visiteurs_tb_publics_v1")
        rows = cursor.fetchall()
    assert len(rows) == 17
    assert rows == snapshot(name="exported rows")


@override_settings(MATOMO_BASE_URL="https://mato.mo", MATOMO_AUTH_TOKEN="foobar")
@pytest.mark.django_db(transaction=True)
@pytest.mark.respx(base_url="https://mato.mo")
@pytest.mark.usefixtures("metabase")
@freeze_time("2022-06-21")
def test_matomo_empty_output(respx_mock, capsys, snapshot):
    MATOMO_ONLINE_EMPTY_CONTENT = "0," * 56 + "0"
    respx_mock.get("/index.php").respond(
        200,
        content=f"{MATOMO_HEADERS}\n{MATOMO_ONLINE_EMPTY_CONTENT}".encode("utf-16"),
    )
    management.call_command("populate_metabase_matomo", wet_run=True)
    stdout, _ = capsys.readouterr()
    # sort the output because it's random (ThreadPoolExecutor)
    assert sorted(stdout.splitlines()) == snapshot(name="empty output")
