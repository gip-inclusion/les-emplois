"""
Helper methods for manipulating dataframes used by both populate_metabase_itou and populate_metabase_fluxiae scripts.
"""

import pandas as pd
from psycopg2 import sql
from tqdm import tqdm

from itou.metabase.management.commands._database_psycopg2 import MetabaseDatabaseCursor
from itou.metabase.management.commands._database_sqlalchemy import get_pg_engine


def switch_table_atomically(table_name):
    with MetabaseDatabaseCursor() as (cur, conn):
        cur.execute(
            sql.SQL("ALTER TABLE IF EXISTS {} RENAME TO {}").format(
                sql.Identifier(table_name), sql.Identifier(f"{table_name}_old")
            )
        )
        cur.execute(
            sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                sql.Identifier(f"{table_name}_new"), sql.Identifier(table_name)
            )
        )
        conn.commit()
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(f"{table_name}_old")))
        conn.commit()


def store_df(df, table_name, dry_run):
    """
    Store dataframe in database.

    Do this chunk by chunk to solve
    psycopg2.OperationalError "server closed the connection unexpectedly" error.
    """
    if dry_run:
        table_name += "_dry_run"
        df = df.head(1000)

    # Recipe from https://stackoverflow.com/questions/44729727/pandas-slice-large-dataframe-in-chunks
    rows_per_chunk = 10 * 1000
    df_chunks = [df[i : i + rows_per_chunk] for i in range(0, df.shape[0], rows_per_chunk)]

    print(f"Storing {table_name} in {len(df_chunks)} chunks of (max) {rows_per_chunk} rows each ...")
    if_exists = "replace"  # For the 1st chunk, drop old existing table if needed.
    for df_chunk in tqdm(df_chunks):
        pg_engine = get_pg_engine()
        df_chunk.to_sql(
            name=f"{table_name}_new",
            # Use a new connection for each chunk to avoid random disconnections.
            con=pg_engine,
            if_exists=if_exists,
            index=False,
            chunksize=1000,
            # INSERT by batch and not one by one. Increases speed x100.
            method="multi",
        )
        pg_engine.dispose()
        if_exists = "append"  # For all other chunks, append to table in progress.

    switch_table_atomically(table_name=table_name)
    print(f"Stored {table_name} in database ({len(df)} rows).")
    print("")


def get_df_from_rows(rows):
    """
    Helper method converting rows into a dataframe.

    Rows should be a list of rows, each row being a Dict (or an OrderedDict to ensure column order) like this one:
    `{"field1": value1, "field2": value2}`
    """
    # `columns=rows[0].keys()` trick is necessary to preserve the order of columns.
    df = pd.DataFrame(rows, columns=rows[0].keys())
    return df
