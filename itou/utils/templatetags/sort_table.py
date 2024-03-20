from django import template

from itou.utils.urls import remove_url_params


register = template.Library()


@register.inclusion_tag("./utils/templatetags/sort_table.html", takes_context=False)
def itou_sort_table(**kwargs):
    """
    render col header with sorting links

    **Tag name**::

        itou_sort_table

    **Parameters**::
        label
            The label for the column.
            Required
        sort
            The name of the sort field.
            Required
    """

    # cleanup sort and order params from current url, before adding new ones to the sorting links
    kwargs["url"] = remove_url_params(kwargs["url"], ["sort", "page"])

    return kwargs
