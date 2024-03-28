from django.utils import timezone


def _str_with_tz(dt):
    return dt.astimezone(timezone.get_current_timezone()).isoformat()
