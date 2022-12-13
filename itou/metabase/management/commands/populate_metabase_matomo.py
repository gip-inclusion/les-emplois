import csv
import datetime
import io
import urllib

import httpx
from dateutil.rrule import MO, WEEKLY, rrule
from django.conf import settings
from django.core.management.base import BaseCommand
from psycopg2 import extras as psycopg2_extras, sql

from itou.metabase.db import MetabaseDatabaseCursor
from itou.utils import constants


DASHBOARDS_TO_DOWNLOAD = {
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

METABASE_DASHBOARDS_TABLE_NAME = "suivi_visiteurs_tb_publics_v0"
METABASE_CUSTOM_VARS_TABLE_NAME = "suivi_visites_custom_vars_v0"


def matomo_api_call(options):
    response = httpx.get(f"{settings.MATOMO_BASE_URL}?{urllib.parse.urlencode(options)}", timeout=MATOMO_TIMEOUT)
    print(response.content)
    csv_content = response.content.decode("utf-16")
    yield from csv.DictReader(io.StringIO(csv_content), dialect="excel")


def update_table_at_date(table_name, column_names, at, rows):
    with MetabaseDatabaseCursor() as (cursor, conn):
        cursor.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {table_name} ({fields_with_type})").format(
                table_name=sql.Identifier(table_name),
                fields_with_type=sql.SQL(",").join(
                    [sql.SQL(" ").join([sql.Identifier(col), sql.SQL("varchar")]) for col in column_names]
                ),
            )
        )
        conn.commit()
        cursor.execute(
            sql.SQL("""DELETE FROM {table_name} WHERE "Date" = {value}""").format(
                table_name=sql.Identifier(table_name),
                col_name=sql.Identifier("Date"),
                value=sql.Literal(str(at)),
            )
        )
        insert_query = sql.SQL("insert into {table_name} ({fields}) values %s").format(
            table_name=sql.Identifier(table_name),
            fields=sql.SQL(",").join(
                [sql.Identifier(col) for col in column_names],
            ),
        )
        psycopg2_extras.execute_values(cursor, insert_query, rows)
        conn.commit()


class Command(BaseCommand):

    help = "Fetches dashboards from matomo and inserts them monday by monday in Metabase in its raw version"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, wet_run=False, **options):
        today = datetime.date.today()
        max_date = datetime.date.today() - datetime.timedelta(days=today.weekday() + 1)

        # NOTE(vperron): if you need to initiate this table, just run the following line with
        # dtstart=datetime.date(2022,1,1)
        for monday in rrule(WEEKLY, byweekday=MO, dtstart=max_date - datetime.timedelta(days=7), until=max_date):
            self._process_matomo_weekly_data(monday.date(), wet_run=wet_run)

    def _process_matomo_weekly_data(self, at, wet_run=False):
        """A helper whose sole purpose is to ease the initialization of all the Matomo tables in metabase.
        Call it with a given week and it's going to do all the initialization.
        """
        column_names = None  # unknown column names initially, they're all the same for every dashboard
        all_rows = []
        base_options = MATOMO_OPTIONS | {
            "date": f"{at}",
            "token_auth": settings.MATOMO_AUTH_TOKEN,
        }

        # for dashboard, public_name in DASHBOARDS_TO_DOWNLOAD.items():
        #     dashboard_options = base_options | {
        #         "idSite": "146",  # pilotage
        #         "segment": f"pageUrl=={constants.PILOTAGE_SITE_URL}/tableaux-de-bord/{dashboard}/",
        #     }
        #     for row in matomo_api_call(dashboard_options):
        #         row["Date"] = at
        #         row["tableau de bord"] = public_name
        #         if not column_names:
        #             column_names = list(row.keys())
        #         all_rows.append(list(row.values()))

        # if wet_run:
        #     update_table_at_date(METABASE_DASHBOARDS_TABLE_NAME, column_names, at, all_rows)

        all_rows = []
        custom_var_options = base_options | {
            "idSite": "117",
            "flat": "1",
            # "method": "CustomVariables.getCustomVariables",
            "method": "Live.getLastVisitsDetails",
            # "segment": f"pageUrl=={constants.PILOTAGE_SITE_URL}/tableaux-de-bord/{dashboard}/",
        }
        for row in matomo_api_call(custom_var_options):
            print(row)
            break
            row["Date"] = at
            column_names = list(row.keys())
            all_rows.append(list(row.values()))

        if wet_run:
            update_table_at_date(METABASE_CUSTOM_VARS_TABLE_NAME, column_names, at, all_rows)
