import pytest
from django.core import management
from django.db import connection
from django.test import override_settings
from freezegun import freeze_time

from itou.metabase import db


@pytest.fixture(name="metabase")
def metabase_fixture(monkeypatch):
    class FakeMetabase:
        """
        This fake metabase database allows us to benefit from all
        the Django heavy lifting that is done with creating the database,
        wrap everything in a transaction, etc.

        This makes us write the metabase tables in the main test database.

        FIXME(vperron): This is very basic for now. It still does not handle
        initial table creation, there might be table name collision or other
        issues. Let's fix them as they arise.
        """

        def __init__(self):
            self.cursor = None

        def __enter__(self):
            self.cursor = connection.cursor().cursor
            return self.cursor, connection

        def __exit__(self, exc_type, exc_value, exc_traceback):
            if self.cursor:
                self.cursor.close()

    monkeypatch.setattr(db, "MetabaseDatabaseCursor", FakeMetabase)


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

MATOMO_CONTENT = (
    "25,26,0,242,43,1,17222,13,132,13,0,43,0%,10.2,12 min 36s,13,110,13,0,24,8%,8.5,9 min 29s,0,0,"
    "17,9,0,0,0,0,2,4,0,65%,0%,0%,0%,35%,27.411,225,111.02,225,7.119,224,149.254,167,178.406,123,"
    "1.025,123,474.235,225,0.12s,0.49s,0.03s,0.89s,1.45s,0.01s,2.11s,0,0,0,0%,0,0,0,0%,0,0,0,0%,"
    "225,95,0,0,17,12,0,0,4%,9.3,11 min 2s"
)


@override_settings(MATOMO_BASE_URL="https://mato.mo")
@pytest.mark.django_db(transaction=True)
@pytest.mark.respx(base_url="https://mato.mo")
@pytest.mark.usefixtures("metabase")
@freeze_time("2022-06-21")
def test_matomo_populate(respx_mock):
    respx_mock.get("/").respond(
        200,
        content=f"{MATOMO_HEADERS}\n{MATOMO_CONTENT}".encode("utf-16"),
    )
    management.call_command(
        "populate_metabase_matomo",
        wet_run=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM suivi_visiteurs_tb_publics_v0")
        rows = cursor.fetchall()
        assert len(rows) == 10
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
            "tb 129 - Analyse des publics",
        )
