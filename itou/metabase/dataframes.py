"""
Helper methods for manipulating dataframes used by both populate_metabase_emplois and
populate_metabase_fluxiae scripts.
"""

import numpy as np
import pandas as pd
from psycopg import sql
from tqdm import tqdm

from itou.metabase.db import MetabaseDatabaseCursor, create_table, get_new_table_name, rename_table_atomically


PANDA_DATAFRAME_TO_PSQL_TYPES_MAPPING = {
    np.int64: "bigint",
    np.object_: "text",
    np.float64: "double precision",
    np.bool_: "boolean",
}


def infer_columns_from_df(df):
    # Generate a dataframe with the same headers a the first non null value for each column
    df_columns = [df[column_name] for column_name in df.columns]
    non_null_values = [df_column.get(df_column.first_valid_index()) for df_column in df_columns]
    initial_line = pd.DataFrame([non_null_values], columns=df.columns)

    # Generate table sql definition from np types
    return [
        (col_name, PANDA_DATAFRAME_TO_PSQL_TYPES_MAPPING[col_type.type])
        for col_name, col_type in initial_line.dtypes.items()
    ]


def store_df(df, table_name, max_attempts=5):
    """
    Store dataframe in database.

    Do this chunk by chunk to solve
    psycopg.OperationalError "server closed the connection unexpectedly" error.

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
            columns = infer_columns_from_df(df)
            create_table(new_table_name, columns, reset=True)
            for df_chunk in tqdm(df_chunks):
                rows = df_chunk.replace({np.nan: None}).to_dict(orient="split")["data"]
                with MetabaseDatabaseCursor() as (cursor, conn):
                    with cursor.copy(
                        sql.SQL("COPY {table_name} FROM STDIN WITH (FORMAT BINARY)").format(
                            table_name=sql.Identifier(new_table_name),
                            Fields=sql.SQL(",").join(
                                [sql.Identifier(col[0]) for col in columns],
                            ),
                        )
                    ) as copy:
                        copy.set_types([col[1] for col in columns])
                        for row in rows:
                            copy.write_row(row)
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
