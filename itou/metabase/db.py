"""
Helper methods for manipulating tables used by both populate_metabase_emplois and populate_metabase_fluxiae scripts.
"""
import logging
import os

import psycopg2
from django.conf import settings
from psycopg2 import sql
from psycopg2.extras import LoggingConnection, LoggingCursor

from itou.utils.python import timeit


logger = logging.getLogger("django.db.backends")


class MetabaseDatabaseCursor:
    def __init__(self):
        self.cursor = None
        self.connection = None

    def __enter__(self):
        self.connection = psycopg2.connect(
            host=settings.METABASE_HOST,
            port=settings.METABASE_PORT,
            dbname=settings.METABASE_DATABASE,
            user=settings.METABASE_USER,
            password=settings.METABASE_PASSWORD,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=5,
            keepalives_count=5,
            connection_factory=LoggingConnection,
        )
        self.connection.initialize(logger)
        self.cursor = self.connection.cursor(cursor_factory=LoggingCursor if settings.SQL_DEBUG else None)
        return self.cursor, self.connection

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()


def get_current_dir():
    return os.path.dirname(os.path.realpath(__file__))


def get_new_table_name(table_name):
    return f"z_new_{table_name}"


def get_old_table_name(table_name):
    return f"z_old_{table_name}"


def switch_table_atomically(table_name):
    """
    Replace table_name with z_new_table_name.
    This allows to take our time filling z_new_table_name without locking table_name.
    """

    with MetabaseDatabaseCursor() as (cur, conn):
        cur.execute(
            sql.SQL("ALTER TABLE IF EXISTS {} RENAME TO {}").format(
                sql.Identifier(table_name),
                sql.Identifier(get_old_table_name(table_name)),
            )
        )
        cur.execute(
            sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                sql.Identifier(get_new_table_name(table_name)),
                sql.Identifier(table_name),
            )
        )
        conn.commit()
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_old_table_name(table_name))))
        conn.commit()


def create_table(table_name: str, columns: list[str, str]):
    """Create table from columns names and types"""
    with MetabaseDatabaseCursor() as (cursor, conn):
        create_table_query = sql.SQL("CREATE TABLE IF NOT EXISTS {table_name} ({fields_with_type})").format(
            table_name=sql.Identifier(table_name),
            fields_with_type=sql.SQL(",").join(
                [sql.SQL(" ").join([sql.Identifier(col_name), sql.SQL(col_type)]) for col_name, col_type in columns]
            ),
        )
        cursor.execute(create_table_query)
        conn.commit()


@timeit
def build_custom_table(table_name, sql_request):
    """
    Build a new table with given sql_request.
    Minimize downtime by building a temporary table first then swap the two tables atomically.
    """
    with MetabaseDatabaseCursor() as (cur, conn):
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_new_table_name(table_name))))
        conn.commit()
        cur.execute(
            sql.SQL("CREATE TABLE {} AS {}").format(
                sql.Identifier(get_new_table_name(table_name)), sql.SQL(sql_request)
            )
        )
        conn.commit()

    switch_table_atomically(table_name=table_name)


def build_final_tables():
    """
    Build final custom tables one by one by playing SQL requests in `sql` folder.

    Typically:
    - 001_fluxIAE_DateDerniereMiseAJour.sql
    - 002_missions_ai_ehpad.sql
    - ...

    The numerical prefixes ensure the order of execution is deterministic.

    The name of the table being created with the query is derived from the filename,
    # e.g. '002_missions_ai_ehpad.sql' => 'missions_ai_ehpad'
    """
    path = f"{get_current_dir()}/sql"
    for filename in sorted([f for f in os.listdir(path) if f.endswith(".sql")]):
        print(f"Running {filename} ...")
        table_name = "_".join(filename.split(".")[0].split("_")[1:])
        with open(os.path.join(path, filename), "r") as file:
            sql_request = file.read()
        build_custom_table(table_name=table_name, sql_request=sql_request)
        print("Done.")
