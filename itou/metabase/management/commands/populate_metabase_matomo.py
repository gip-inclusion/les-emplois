import concurrent
import csv
import datetime
import io
import urllib
from dataclasses import dataclass
from time import sleep

import httpx
import tenacity
from dateutil.rrule import MO, WEEKLY, rrule
from django.conf import settings
from django.core.management.base import BaseCommand
from psycopg2 import extras as psycopg2_extras, sql

from itou.common_apps.address.departments import (
    DEPARTMENT_TO_REGION,
    DEPARTMENTS,
    REGIONS,
    format_region_and_department_for_matomo,
    format_region_for_matomo,
)
from itou.metabase.db import MetabaseDatabaseCursor, create_table
from itou.utils import constants


def log_retry_attempt(retry_state):
    try:
        outcome = retry_state.outcome.result()
    except Exception as e:  # pylint: disable=broad-except
        outcome = str(e)

    print(f"attempt={retry_state.attempt_number} failed with outcome={outcome}")


# Matomo might be a little tingly sometimes, let's give it retries.
httpx_transport = httpx.HTTPTransport(retries=3)
client = httpx.Client(transport=httpx_transport)

PUBLIC_DASHBOARDS = {
    "analyse-des-publics": "tb 129 - Analyse des publics",
    "auto-prescription": "tb 32 - Acceptés en auto-prescription",
    "etat-suivi-candidatures": "tb 116 - Recrutement",
    "etp-conventionnes": "tb 140 - ETP conventionnés",
    "metiers": "tb 90 - Analyse des métiers",
    "postes-en-tension": "tb 150 - Fiches de poste en tension",
    "prescripteurs-habilites": "tb 136 - Prescripteurs habilités",
    "statistiques-emplois": "tb 43 - Statistiques des emplois",
    "zoom-employeurs": "tb 54 - Typologie des employeurs",
    "zoom-prescripteurs": "tb 52 - Typologie de prescripteurs",
}

PRIVATE_DEPARTMENT_DASHBOARDS = {
    "stats/cd/{}": "tb 118 - Données IAE CD",
    "stats/ddets/hiring/{}": "tb 160 - Facilitation de l'embauche DREETS/DDETS",
    "stats/ddets/iae/{}": "tb 117 - Données IAE DREETS/DDETS",
    "stats/pe/conversion/main/{}": "tb 169 - Taux de transformation PE",
    "stats/pe/delay/main/{}": "tb 168 - Délai d'entrée en IAE",
    "stats/pe/state/main/{}": "tb 149 - Candidatures orientées PE",
    "stats/pe/tension/{}": "tb 162 - Fiches de poste en tension PE",
    "stats/siae/hiring/{}": "tb 165 - Recrutement SIAE",
}

PRIVATE_REGION_DASHBOARDS = {
    "stats/dreets/hiring/{}": "tb 160 - Facilitation de l'embauche DREETS/DDETS",
    "stats/dreets/iae/{}": "tb 117 - Données IAE DREETS/DDETS",
    "stats/pe/conversion/main/{}/drpe": "tb 169 - Taux de transformation PE",
    "stats/pe/delay/main/{}/drpe": "tb 168 - Délai d'entrée en IAE",
    "stats/pe/state/main/{}/drpe": "tb 149 - Candidatures orientées PE",
    "stats/pe/tension/{}/drpe": "tb 162 - Fiches de poste en tension PE",
}


MATOMO_OPTIONS = {
    "expanded": 1,
    "filter_limit": -1,
    "format": "CSV",
    "format_metrics": 1,
    "language": "en",
    "method": "API.get",
    "module": "API",
    "period": "week",
    "translateColumnNames": 1,
}

MATOMO_TIMEOUT = 60  # in seconds. Matomo can be slow.

METABASE_PUBLIC_DASHBOARDS_TABLE_NAME = "suivi_visiteurs_tb_publics_v0"
METABASE_PRIVATE_DASHBOARDS_TABLE_NAME = "suivi_visiteurs_tb_prives_v0"


def matomo_api_call(options):
    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_fixed(30), after=log_retry_attempt)
    def get_csv_raw_data():
        response = client.get(f"{settings.MATOMO_BASE_URL}?{urllib.parse.urlencode(options)}", timeout=MATOMO_TIMEOUT)
        response.raise_for_status()
        return response.content.decode("utf-16")

    yield from csv.DictReader(io.StringIO(get_csv_raw_data()), dialect="excel")


def update_table_at_date(table_name, column_names, at, rows):
    create_table(
        table_name,
        [(col_name, "varchar") for col_name in column_names],
    )
    with MetabaseDatabaseCursor() as (cursor, conn):
        cursor.execute(
            sql.SQL("""DELETE FROM {table_name} WHERE "Date" = {value}""").format(
                table_name=sql.Identifier(table_name),
                col_name=sql.Identifier("Date"),
                value=sql.Literal(str(at)),
            )
        )
        insert_query = sql.SQL("INSERT INTO {table_name} ({fields}) VALUES %s").format(
            table_name=sql.Identifier(table_name),
            fields=sql.SQL(",").join(
                [sql.Identifier(col) for col in column_names],
            ),
        )
        psycopg2_extras.execute_values(cursor, insert_query, rows)
        conn.commit()


@dataclass
class MatomoFetchOptions:
    dashboard_name: str
    api_options: str
    extra_columns: dict


def get_matomo_dashboard(at: datetime.datetime, options: MatomoFetchOptions):
    base_options = MATOMO_OPTIONS | {
        "date": f"{at}",
        "token_auth": settings.MATOMO_AUTH_TOKEN,
    }
    segment = options.api_options.get("segment")
    if segment:
        segment = segment.split("==")[1]
    print(f"\t> fetching date={at} dashboard='{options.dashboard_name}' segment={segment}")
    column_names = None
    results = []
    for row in matomo_api_call(base_options | options.api_options):
        if all(x in ["0", "0s", "0%"] for x in row.values()):
            print(f"\t! empty matomo values for date={at} dashboard={options.dashboard_name}")
            return None, None
        row["Date"] = at
        row["Tableau de bord"] = options.dashboard_name
        for extra_col, extra_value in options.extra_columns.items():
            row[extra_col] = extra_value
        if not column_names:
            column_names = list(row.keys())
        results.append(list(row.values()))
    # The private dashboards are so many that we need to sleep before 2 calls, as Matomo
    # severely limits the client request rate to the point of the timeout (10 minutes for a single call)
    # Introducing a delay of 1 second between the calls drops the complete fetch from impossible (timeout
    # after 2 hours) to less than 5 minutes.
    sleep(1)
    return column_names, results


def multiget_matomo_dashboards(at: datetime.datetime, dashboard_options: list[MatomoFetchOptions]):
    all_rows = []
    column_names = None
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(
                get_matomo_dashboard,
                at,
                options,
            )
            for options in dashboard_options
        ]
        for future in concurrent.futures.as_completed(futures, timeout=600):  # 10 minutes max for a dashboard
            cols, rows = future.result()
            if rows is None:
                continue
            # redefine column_names every time, they should always be the same
            column_names = cols
            all_rows += rows
    return column_names, all_rows


class Command(BaseCommand):

    help = "Fetches dashboards from matomo and inserts them monday by monday in Metabase in its raw version"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.MODE_TO_OPERATION = {
            "public": self._fetch_matomo_public_dashboards,
            "private": self._fetch_matomo_private_dashboards,
        }

    def add_arguments(self, parser):
        parser.add_argument("--mode", action="store", dest="mode", type=str, choices=self.MODE_TO_OPERATION.keys())
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, mode, wet_run, **options):
        today = datetime.date.today()
        max_date = datetime.date.today() - datetime.timedelta(days=today.weekday() + 1)
        # NOTE(vperron): if you need to initiate this table, just run the following line with
        # dtstart=datetime.date(2022,1,1)
        for monday in rrule(WEEKLY, byweekday=MO, dtstart=max_date - datetime.timedelta(days=7), until=max_date):
            self.MODE_TO_OPERATION[mode](monday.date(), wet_run=wet_run)

    def _fetch_matomo_public_dashboards(self, at, wet_run=False):
        api_call_options = []
        for url_path, dashboard_name in PUBLIC_DASHBOARDS.items():
            api_call_options.append(
                MatomoFetchOptions(
                    dashboard_name,
                    {
                        "idSite": constants.MATOMO_SITE_PILOTAGE_ID,
                        "segment": f"pageUrl=={constants.PILOTAGE_SITE_URL}/tableaux-de-bord/{url_path}/",
                    },
                    {},
                )
            )

        self.stdout.write(f"> about to fetch count={len(api_call_options)} public dashboards from Matomo.")
        column_names, all_rows = multiget_matomo_dashboards(at, api_call_options)
        if wet_run:
            update_table_at_date(
                METABASE_PUBLIC_DASHBOARDS_TABLE_NAME,
                column_names,
                at,
                sorted(all_rows, key=lambda r: r[-1]),  # sort by dashboard name
            )

    def _fetch_matomo_private_dashboards(self, at, wet_run=False):
        base_options = {"idSite": constants.MATOMO_SITE_EMPLOIS_ID}
        base_extra_columns = {
            "Nom Département": None,
            "Département": None,
            "Région": None,  # NOTE(vperron): Region is added even though it's not in the current table
        }
        api_call_options = [
            MatomoFetchOptions(
                "TB DGEFP",
                base_options
                | {
                    "segment": f"pageUrl=={constants.EMPLOIS_SITE_URL}/stats/dgefp/iae/",
                },
                base_extra_columns,
            )
        ]

        def _options_from_url_path(url_path):
            return base_options | {
                "segment": f"pageUrl=={constants.EMPLOIS_SITE_URL}/{url_path}",
            }

        for region, departments in REGIONS.items():
            region_url_path = format_region_for_matomo(region)
            for url_path_fmt, dashboard_name in PRIVATE_REGION_DASHBOARDS.items():
                url_path = url_path_fmt.format(region_url_path)
                extra_columns = base_extra_columns | {
                    "Région": region,
                }
                api_call_options.append(
                    MatomoFetchOptions(
                        dashboard_name,
                        _options_from_url_path(url_path),
                        extra_columns,
                    )
                )

            for department in departments:
                dpt_url_path = format_region_and_department_for_matomo(department)
                for url_path_fmt, dashboard_name in PRIVATE_DEPARTMENT_DASHBOARDS.items():
                    url_path = url_path_fmt.format(dpt_url_path)
                    extra_columns = {
                        "Nom Département": DEPARTMENTS[department],
                        "Département": department,
                        "Région": DEPARTMENT_TO_REGION[department],
                    }
                    api_call_options.append(
                        MatomoFetchOptions(
                            dashboard_name,
                            _options_from_url_path(url_path),
                            extra_columns,
                        )
                    )

        self.stdout.write(f"> about to fetch count={len(api_call_options)} private dashboards from Matomo.")
        column_names, all_rows = multiget_matomo_dashboards(at, api_call_options)
        if wet_run:
            update_table_at_date(
                METABASE_PRIVATE_DASHBOARDS_TABLE_NAME,
                column_names,
                at,
                sorted(all_rows, key=lambda r: (r[-3] or "", r[-4])),  # sort by department if any, then dashboard name
            )
