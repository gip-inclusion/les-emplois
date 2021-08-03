import psycopg2
from django.conf import settings


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
        )
        self.cursor = self.connection.cursor()
        return self.cursor, self.connection

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.cursor.close()
        self.connection.close()
