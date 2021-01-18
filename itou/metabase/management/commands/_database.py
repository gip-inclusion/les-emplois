import psycopg2
from django.conf import settings
from sqlalchemy import create_engine


# Required for using pandas.to_sql method in `populate_metabase_fluxiae.py`.
PG_ENGINE = create_engine(
    f"postgresql://{settings.METABASE_USER}:{settings.METABASE_PASSWORD}"
    f"@{settings.METABASE_HOST}:{settings.METABASE_PORT}/{settings.METABASE_DATABASE}"
)


class MetabaseDatabaseCursor:
    def __enter__(self):
        self.conn = psycopg2.connect(
            host=settings.METABASE_HOST,
            port=settings.METABASE_PORT,
            dbname=settings.METABASE_DATABASE,
            user=settings.METABASE_USER,
            password=settings.METABASE_PASSWORD,
        )
        self.cur = self.conn.cursor()
        return self.cur, self.conn

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.conn.commit()
        self.cur.close()
        self.conn.close()
