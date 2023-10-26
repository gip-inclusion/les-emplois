"""
This can come in handy for instance to compare two Metabase tables,
before and after a big change can be a good idea

For the record, we then used

    cd before
    for file in $(ls); do echo "splitting $file"; sort $file | split -C 5m --numeric-suffixes - $file; rm $file; done
    cd ../after
    for file in $(ls); do echo "splitting $file"; sort $file | split -C 5m --numeric-suffixes - $file; rm $file; done
    cd ..
    for f in $(ls before); do diff -q before/$f after/$f; done

To do the final comparison. Meld or vimdiff can be used to inspect what's wrong.
"""

import os

from psycopg import sql

from itou.metabase.db import MetabaseDatabaseCursor
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Dumps Metabase database to stable CSV-like files"

    def add_arguments(self, parser):
        parser.add_argument("--prefix", action="store", dest="prefix", type=str)
        parser.add_argument("--table_name", action="store", dest="table_name", type=str)

    def handle(self, prefix, table_name, **kwargs):
        with MetabaseDatabaseCursor() as (cursor, _conn):
            self.stdout.write(f"exporting {table_name=}")
            cursor.execute(
                sql.SQL(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = {table_name};"
                ).format(
                    table_name=sql.Literal(table_name),
                )
            )
            column_names = sorted([str(d[0]) for d in cursor.fetchall()])
            if prefix:
                os.makedirs(prefix, exist_ok=True)
                filename = f"{prefix}/{table_name}.csv"
            else:
                filename = f"{table_name}.csv"
            with open(filename, mode="w", encoding="utf-8") as f:
                cursor.copy_to(f, table_name, sep=";", null="\\\\N", columns=column_names)
