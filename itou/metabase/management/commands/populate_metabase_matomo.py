import concurrent
import csv
import datetime
import io
import threading
import urllib
from dataclasses import dataclass

import httpx
import tenacity
from django.conf import settings
from psycopg import sql
from sentry_sdk.crons import monitor

from itou.metabase.db import MetabaseDatabaseCursor, create_table
from itou.utils import constants
from itou.utils.command import BaseCommand
from itou.utils.date import monday_of_the_week


lock = threading.Lock()


def threadsafe_print(s):
    with lock:
        print(s, flush=True)


def log_retry_attempt(retry_state):
    try:
        outcome = retry_state.outcome.result()
    except Exception as e:
        outcome = str(e)
    threadsafe_print(f"attempt={retry_state.attempt_number} failed with outcome={outcome}")


# Matomo might be a little tingly sometimes, let's give it retries.
httpx_transport = httpx.HTTPTransport(retries=3)
client = httpx.Client(transport=httpx_transport)

PUBLIC_DASHBOARDS = {
    "auto-prescription": "tb 32 - Acceptés en auto-prescription",
    "statistiques-emplois": "tb 43 - Statistiques des emplois",
    "zoom-prescripteurs": "tb 52 - Typologie de prescripteurs",
    "zoom-employeurs": "tb 54 - Typologie des employeurs",
    "metiers": "tb 90 - Analyse des métiers",
    "etat-suivi-candidatures": "tb 116 - Recrutement",
    "analyse-des-publics": "tb 129 - Analyse des publics",
    "prescripteurs-habilites": "tb 136 - Prescripteurs habilités",
    "etp-conventionnes": "tb 140 - ETP conventionnés",
    "suivi-controle-a-posteriori": "tb 144 - Contrôle à posteriori",
    "postes-en-tension": "tb 150 - Fiches de poste en tension",
    "femmes-iae": "tb 216 - Les femmes dans l'IAE",
    "suivi-pass-iae": "tb 217 - Suivi pass IAE",
    "cartographies-iae": "tb 218 - Cartographie de l'IAE",
    "conventionnements-iae": "tb 287 - Conventionnements IAE",
    "zoom-esat": "tb 306 - Zoom sur les ESAT",
    "analyses-conventionnements-iae": "tb 325 - Analyses autour des conventionnements IAE",
    "suivi-demandes-prolongation": "tb 336 - Suivi des prolongations",
    "bilan-candidatures-iae": "tb 337 - Bilan de la phase de candidatures en IAE",
    "requetage-ft": "tb 406 - Requêtage des données de l'expérimentation RSA",
    "candidat-file-active-IAE": "tb 408 - Candidats dans la file active",
    "zoom-esat-24": "tb 471 - Zoom sur les ESAT (2024)",
    # Note: keep those commented for reference. They're not used anymore but if we ever
    # need to regenerate values for the Q1 2022 or before, they're going to be required.
    # "recrutement": "tb 116 - Recrutement",
    # "criteres": "tb 32 - Acceptés en auto-prescription",
    # "prescripteurs": "tb 52 - Typologie de prescripteurs",
    # "employeurs": "tb 54 - Typologie des employeurs",
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

METABASE_PUBLIC_DASHBOARDS_TABLE_NAME = "suivi_visiteurs_tb_publics_v1"


def matomo_api_call(options):
    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_fixed(30), after=log_retry_attempt)
    def get_csv_raw_data():
        url = urllib.parse.urljoin(settings.MATOMO_BASE_URL, "index.php")
        return (
            client.get(f"{url}?{urllib.parse.urlencode(options)}", timeout=MATOMO_TIMEOUT)
            .raise_for_status()
            .content.decode("utf-16")
        )

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
        with cursor.copy(
            sql.SQL("COPY {table_name} ({fields}) FROM STDIN").format(
                table_name=sql.Identifier(table_name),
                fields=sql.SQL(",").join(
                    [sql.Identifier(col) for col in column_names],
                ),
            )
        ) as copy:
            for row in rows:
                copy.write_row(row)
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
        key, value = segment.split("==")
        options.api_options["segment"] = f"{key}=={urllib.parse.quote(value, safe='')}"
    threadsafe_print(f"\t> fetching date={at} dashboard='{options.dashboard_name}' {key}={value}")
    column_names = None
    results = []
    for row in matomo_api_call(base_options | options.api_options):
        if all(x in ["0", "0s", "0%", None] for x in row.values()):
            threadsafe_print(f"\t! empty matomo values for date={at} dashboard={options.dashboard_name}")
            continue
        row["Date"] = at
        row["Tableau de bord"] = options.dashboard_name
        for extra_col, extra_value in options.extra_columns.items():
            row[extra_col] = extra_value
        if not column_names:
            column_names = list(row.keys())
        results.append(list(row.values()))
    return column_names, results


def multiget_matomo_dashboards(at: datetime.datetime, dashboard_options: list[MatomoFetchOptions]):
    all_rows = []
    column_names = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                get_matomo_dashboard,
                at,
                options,
            )
            for options in dashboard_options
        ]
        for future in concurrent.futures.as_completed(futures, timeout=60 * 60 * 3):  # 3h max for all dashboards
            cols, rows = future.result()
            if not cols or not rows:
                continue
            # redefine column_names every time, they should always be the same
            column_names = cols
            all_rows += rows
    return column_names, all_rows


class Command(BaseCommand):
    help = "Fetches dashboards from matomo and inserts them monday by monday in Metabase in its raw version"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @monitor(
        monitor_slug="populate-metabase-matomo",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 2 * * MON"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, *, wet_run, **options):
        last_week_monday = monday_of_the_week() - datetime.timedelta(days=7)

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

        threadsafe_print(f"> about to fetch count={len(api_call_options)} public dashboards from Matomo.")
        column_names, all_rows = multiget_matomo_dashboards(last_week_monday, api_call_options)
        if wet_run and column_names:
            update_table_at_date(
                METABASE_PUBLIC_DASHBOARDS_TABLE_NAME,
                column_names,
                last_week_monday,
                sorted(all_rows, key=lambda r: r[-1]),  # sort by dashboard name
            )
