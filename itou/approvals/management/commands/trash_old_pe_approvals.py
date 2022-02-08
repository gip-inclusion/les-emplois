from django.core.management.base import BaseCommand
from django.db import connection
from psycopg2 import sql


def get_old_table_name(table_name):
    """
    We use the `z` prefix so that temporary tables are listed last and do not get in the way of Metabase power users.
    """
    return f"z_old_{table_name}"


class Command(BaseCommand):
    def handle(self, dry_run=False, reset=False, **options):
        table_name = "approvals_poleemploiapproval"
        merged_table_name = "merged_approvals_poleemploiapproval"

        cursor = connection.cursor()
        cursor.execute(
            sql.SQL("ALTER TABLE IF EXISTS {} RENAME TO {}").format(
                sql.Identifier(table_name),
                sql.Identifier(get_old_table_name(table_name)),
            )
        )
        cursor.execute(
            sql.SQL("ALTER TABLE IF EXISTS {} RENAME TO {}").format(
                sql.Identifier(merged_table_name),
                sql.Identifier(table_name),
            )
        )

        connection.commit()
        cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_old_table_name(table_name))))
        connection.commit()
