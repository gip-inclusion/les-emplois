from django.conf import settings
from django.utils.http import is_safe_url


def get_safe_url(request, param_name, default="/"):
    next_url = request.GET.get(param_name) or request.POST.get(param_name)
    if next_url and is_safe_url(
        url=next_url,
        allowed_hosts=settings.ALLOWED_HOSTS,
        require_https=request.is_secure(),
    ):
        return next_url
    return default
