from rest_framework import pagination


class PageNumberPagination(pagination.PageNumberPagination):
    """
    We use a global per-page pagination.
    Since DRF 3.1, the global PAGINATE_BY_PARAM setting is deprecated in favor of customizing
    a paginator
    https://www.django-rest-framework.org/community/3.1-announcement/#pagination
    """

    page_size_query_param = "page_size"
