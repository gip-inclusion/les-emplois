from django.conf import settings
from sqlalchemy import create_engine


"""
Required for using pandas.to_sql method in `populate_metabase_fluxiae.py`.

As stated in https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.to_sql.html
pd.to_sql expects a sqlalchemy engine, not our usual psycopg2 engine.
So we have to use sqlalchemy just for this purpose ¬_¬

See also https://stackoverflow.com/questions/23103962/how-to-write-dataframe-to-postgres-table

More generally, pandas requires SQLAlchemy to be installed for SQL operations:

Quoting: https://pandas.pydata.org/pandas-docs/stable/user_guide/io.html#sql-queries
`Database abstraction is provided by SQLAlchemy if installed.
If SQLAlchemy is not installed, a fallback is only provided for sqlite`
"""


def get_pg_engine():
    return create_engine(
        f"postgresql://{settings.METABASE_USER}:{settings.METABASE_PASSWORD}"
        f"@{settings.METABASE_HOST}:{settings.METABASE_PORT}/{settings.METABASE_DATABASE}",
        # Reduce likelyhood of random disconnections.
        # See https://docs.sqlalchemy.org/en/13/core/pooling.html#pool-disconnects
        pool_pre_ping=True,
    )
