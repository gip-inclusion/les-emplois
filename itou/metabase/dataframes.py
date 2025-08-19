"""
Helper methods for manipulating dataframes used by the populate_metabase_emplois script.
"""

import logging
import time

import numpy as np
import pandas as pd
from psycopg import sql

from itou.metabase.db import MetabaseDatabaseCursor, create_table, get_new_table_name, rename_table_atomically


logger = logging.getLogger(__name__)


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


def store_df(df, table_name, batch_size=10_000):
    """
    Store dataframe in database.

    Do this chunk by chunk to solve
    psycopg.OperationalError "server closed the connection unexpectedly" error.
    """
    start_time = time.perf_counter()

    # Drop unnamed columns
    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

    columns = infer_columns_from_df(df)
    logger.info("Injecting %i rows with %i columns into %r", len(df), len(columns), table_name)

    new_table_name = get_new_table_name(table_name)
    create_table(new_table_name, columns, reset=True)

    with MetabaseDatabaseCursor() as (cursor, conn):
        written_rows = 0
        # Recipe from https://stackoverflow.com/questions/44729727/pandas-slice-large-dataframe-in-chunks
        for df_chunk in [df[i : i + batch_size] for i in range(0, df.shape[0], batch_size)]:
            chunk_start_time = time.perf_counter()
            rows = df_chunk.replace({np.nan: None}).to_dict(orient="split")["data"]
            with cursor.copy(
                sql.SQL("COPY {new_table_name} ({fields}) FROM STDIN WITH (FORMAT BINARY)").format(
                    new_table_name=sql.Identifier(new_table_name),
                    fields=sql.SQL(",").join(
                        [sql.Identifier(col[0]) for col in columns],
                    ),
                )
            ) as copy:
                copy.set_types([col[1] for col in columns])
                for row in rows:
                    copy.write_row(row)
            conn.commit()
            written_rows += len(df_chunk)
            logger.info(
                "%r: %i of %i rows written in %0.2f seconds",
                table_name,
                written_rows,
                len(df),
                time.perf_counter() - chunk_start_time,
            )

    rename_table_atomically(new_table_name, table_name)
    logger.info("%r created in %0.2f seconds", table_name, time.perf_counter() - start_time)


def get_df_from_rows(rows):
    """
    Helper method converting rows into a dataframe.

    Rows should be a list of rows, each row being a Dict (or an OrderedDict to ensure column order) like this one:
    `{"field1": value1, "field2": value2}`
    """
    # `columns=rows[0].keys()` trick is necessary to preserve the order of columns.
    df = pd.DataFrame(rows, columns=rows[0].keys())
    return df
