from django.db.models import Q


def or_queries(queries, required=True):
    if required and not queries:
        raise ValueError("Filter queries must not be empty.")
    return Q.create(queries, connector=Q.OR)


def dictfetchall(cursor):
    """
    Return all rows from a cursor as a dict.
    Assume the column names are unique.

    Source: https://docs.djangoproject.com/en/dev/topics/db/sql/#executing-custom-sql-directly
    """
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
