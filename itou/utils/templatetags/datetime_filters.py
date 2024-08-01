from django import template


register = template.Library()


@register.filter
def duration(value):
    """
    Return a simple humanized form of datetime.timedelta
    """
    if total_seconds := value.total_seconds():
        hours = int(total_seconds / 3_600)
        minutes = int((total_seconds % 3600) / 60)

        if hours and minutes:
            return f"{hours}h{minutes}"
        if hours:
            return f"{hours}h"
        if minutes:
            return f"{minutes} min"

    return "N/A"
