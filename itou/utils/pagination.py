from django.core.paginator import EmptyPage, InvalidPage, Page, Paginator


class ItouPaginator(Paginator):
    def __init__(self, object_list, per_page, orphans=0, allow_empty_first_page=True, max_pages_num=10):
        super().__init__(object_list, per_page, orphans=orphans, allow_empty_first_page=allow_empty_first_page)
        self.max_pages_num = max_pages_num

    def _get_page(self, *args, **kwargs):
        return ItouPage(*args, **kwargs)


class ItouPage(Page):
    def __init__(self, object_list, number, paginator):
        super().__init__(object_list, number, paginator)

        total_pages = paginator.num_pages
        if total_pages <= paginator.max_pages_num:
            pages_to_display = paginator.page_range
        else:
            first = number - (paginator.max_pages_num // 2)
            last = first + paginator.max_pages_num
            if first <= 0:
                first = 1
                last = first + paginator.max_pages_num
            elif last >= total_pages:
                last = total_pages
                first = last - paginator.max_pages_num
            pages_to_display = range(first, last + 1)

        self.pages_to_display = pages_to_display
        self.display_pager = total_pages > 1


def pager(queryset, page, items_per_page=10, pages_num=10):
    """
    A generic pager built on top of Django core's Paginator.
    https://docs.djangoproject.com/en/dev/topics/pagination/

    Arguments:
        queryset: QuerySet, a queryset object to paginate
        page: int, current page number
        items_per_page: int, number of items per page
        pages_num: int, number of pages to display

    Returns:
        custom_pager: a django.core.paginator.Page instance with a few additional attributes:
            pages_to_display: list, allow to iterate and create a google-style pager
            display_pager: bool, True if there are more than one page to display
    """
    paginator = ItouPaginator(queryset, items_per_page, max_pages_num=pages_num)

    try:
        page = int(page)
    except (ValueError, TypeError):
        page = 1

    total_pages = paginator.num_pages

    try:
        return paginator.page(page)
    except (EmptyPage, InvalidPage):
        # If page request is out of range, deliver last page of results.
        return paginator.page(total_pages)
