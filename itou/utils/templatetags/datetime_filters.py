from datetime import date, datetime

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


@register.filter(expects_localtime=True)
def naturaldate(value):
    """
    For date values that are tomorrow, today or yesterday compared to present day return representing string.
    Otherwise, return a string formatted according to the most representative delta in days/months/years.
    """
    tzinfo = getattr(value, "tzinfo", None)
    try:
        value = date(value.year, value.month, value.day)
    except AttributeError:
        # Passed value wasn't a date object
        return value
    today = datetime.now(tzinfo).date()
    delta = value - today
    abs_days_delta = abs(delta.days)
    if delta.days == 0:
        return "aujourd’hui"
    elif delta.days == 1:
        return "demain"
    elif delta.days == -1:
        return "hier"
    elif abs_days_delta < 30:
        return f"{'dans' if delta.days > 0 else 'il y a'} {abs_days_delta} jour{'s' if abs_days_delta > 1 else ''}"
    elif abs_days_delta < 365:
        months = abs_days_delta // 30
        return f"{'dans' if delta.days > 0 else 'il y a'} {months} mois"
    else:
        years = abs_days_delta // 365
        return f"{'dans' if delta.days > 0 else 'il y a'} {years} an{'s' if years > 1 else ''}"
