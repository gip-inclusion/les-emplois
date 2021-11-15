"""
Helper methods for manipulating tables used by both populate_metabase_itou and populate_metabase_fluxiae scripts.
"""
from psycopg2 import sql

from itou.metabase.management.commands._database_psycopg2 import MetabaseDatabaseCursor


def get_new_table_name(table_name):
    """
    We use the `z` prefix so that temporary tables are listed last and do not get in the way of Metabase power users.
    """
    return f"z_new_{table_name}"


def get_old_table_name(table_name):
    """
    We use the `z` prefix so that temporary tables are listed last and do not get in the way of Metabase power users.
    """
    return f"z_old_{table_name}"


def get_dry_table_name(table_name):
    """
    We use the `z` prefix so that temporary tables are listed last and do not get in the way of Metabase power users.
    """
    return f"z_dry_{table_name}"


def switch_table_atomically(table_name):
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
        # Dry run tables are periodically dropped by wet runs.
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_dry_table_name(table_name))))
        conn.commit()
