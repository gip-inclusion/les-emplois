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
    "filter_limit": 400,
    "format": "CSV",
    "format_metrics": 1,
    "idSite": "146",  # pilotage
    "language": "en",
    "method": "API.get",
    "module": "API",
    "period": "week",
    "translateColumnNames": 1,
}

MATOMO_TIMEOUT = 60  # in seconds. Matomo can be slow.

METABASE_TABLE_NAME = "suivi_visiteurs_tb_publics_v0"


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
            self._fetch_matomo_row(monday.date(), wet_run=wet_run)

    def _fetch_matomo_row(self, at, wet_run=False):
        MATOMO_COLUMNS = None
        all_rows = []

        for dashboard, public_name in DASHBOARDS_TO_DOWNLOAD.items():
            options_dict = MATOMO_OPTIONS | {
                "date": f"{at}",
                "segment": f"pageUrl=={constants.PILOTAGE_SITE_URL}/tableaux-de-bord/{dashboard}/",
                "token_auth": settings.MATOMO_AUTH_TOKEN,
            }
            response = httpx.get(
                f"{settings.MATOMO_BASE_URL}?{urllib.parse.urlencode(options_dict)}", timeout=MATOMO_TIMEOUT
            )
            csv_content = response.content.decode("utf-16")
            reader = csv.DictReader(io.StringIO(csv_content), dialect="excel")
            for row in reader:
                row["Date"] = at
                row["tableau de bord"] = public_name
                if not MATOMO_COLUMNS:
                    MATOMO_COLUMNS = list(row.keys())
                all_rows.append(list(row.values()))

        if wet_run:
            with MetabaseDatabaseCursor() as (cursor, conn):
                cursor.execute(
                    sql.SQL("CREATE TABLE IF NOT EXISTS {table_name} ({fields_with_type})").format(
                        table_name=sql.Identifier(METABASE_TABLE_NAME),
                        fields_with_type=sql.SQL(",").join(
                            [sql.SQL(" ").join([sql.Identifier(col), sql.SQL("varchar")]) for col in MATOMO_COLUMNS]
                        ),
                    )
                )
                conn.commit()
                cursor.execute(
                    sql.SQL("""DELETE FROM {table_name} WHERE "Date" = {value}""").format(
                        table_name=sql.Identifier(METABASE_TABLE_NAME),
                        col_name=sql.Identifier("Date"),
                        value=sql.Literal(str(at)),
                    )
                )
                insert_query = sql.SQL("insert into {table_name} ({fields}) values %s").format(
                    table_name=sql.Identifier(METABASE_TABLE_NAME),
                    fields=sql.SQL(",").join(
                        [sql.Identifier(col) for col in MATOMO_COLUMNS],
                    ),
                )
                psycopg2_extras.execute_values(cursor, insert_query, all_rows)
                conn.commit()
