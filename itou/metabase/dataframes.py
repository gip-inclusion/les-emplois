"""
Helper methods for manipulating dataframes used by both populate_metabase_emplois and
populate_metabase_fluxiae scripts.
"""
import csv
from io import StringIO

import numpy as np
import pandas as pd
from psycopg2 import sql
from tqdm import tqdm

from itou.metabase.db import MetabaseDatabaseCursor, create_table, get_new_table_name, rename_table_atomically


PANDA_DATAFRAME_TO_PSQL_TYPES_MAPPING = {
    np.int64: "BIGINT",
    np.object0: "TEXT",
    np.float64: "DOUBLE PRECISION",
    np.bool8: "BOOLEAN",
}


def infer_colomns_from_df(df):
    # Generate a dataframe with the same headers a the first non null value for each colomn
    df_columns = [df[column_name] for column_name in df.columns]
    non_null_values = [df_column.get(df_column.first_valid_index()) for df_column in df_columns]
    initial_line = pd.DataFrame([non_null_values], columns=df.columns)

    # Generate table sql definition from np types
    return [
        (col_name, PANDA_DATAFRAME_TO_PSQL_TYPES_MAPPING[col_type.type])
        for col_name, col_type in initial_line.dtypes.items()
    ]


def init_table(df, table_name):
    with MetabaseDatabaseCursor() as (cursor, conn):
        cursor.execute(sql.SQL("DROP TABLE IF EXISTS {table_name}").format(table_name=sql.Identifier(table_name)))
        conn.commit()
    # Generate table
    create_table(table_name, infer_colomns_from_df(df))


def store_df(df, table_name, max_attempts=5):
    """
    Store dataframe in database.

    Do this chunk by chunk to solve
    psycopg2.OperationalError "server closed the connection unexpectedly" error.

    Try up to `max_attempts` times.
    """
    # Recipe from https://stackoverflow.com/questions/44729727/pandas-slice-large-dataframe-in-chunks
    rows_per_chunk = 10 * 1000
    df_chunks = [df[i : i + rows_per_chunk] for i in range(0, df.shape[0], rows_per_chunk)]

    print(f"Storing {table_name} in {len(df_chunks)} chunks of (max) {rows_per_chunk} rows each ...")

    attempts = 0

    new_table_name = get_new_table_name(table_name)
    while attempts < max_attempts:
        try:
            init_table(df, new_table_name)
            for df_chunk in tqdm(df_chunks):
                buffer = StringIO()
                df_chunk.to_csv(buffer, header=False, index=False, sep="\t", quoting=csv.QUOTE_NONE, escapechar="\\")
                buffer.seek(0)
                with MetabaseDatabaseCursor() as (cursor, conn):
                    cursor.copy_from(buffer, new_table_name, sep="\t", null="")
                    conn.commit()
            break
        except Exception as e:
            # Catching all exceptions is a generally a code smell but we eventually reraise it so it's ok.
            attempts += 1
            print(f"Attempt #{attempts} failed with exception {repr(e)}.")
            if attempts == max_attempts:
                print("No more attemps left, giving up and raising the exception.")
                raise
            print("New attempt started...")

    rename_table_atomically(new_table_name, table_name)
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
