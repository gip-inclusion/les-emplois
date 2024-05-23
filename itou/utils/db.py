from django.db.models import Q


def or_queries(queries, required=True):
    if required and not queries:
        raise ValueError("Filter queries must not be empty.")
    return Q.create(queries, connector=Q.OR)
