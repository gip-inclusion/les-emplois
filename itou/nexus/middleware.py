from django.core.cache import cache
from django.urls import reverse
from itoutils.django.nexus.middleware import BaseAutoLoginMiddleware

from itou.nexus.utils import dropdown_status
from itou.users.enums import UserKind
from itou.users.models import User


class AutoLoginMiddleware(BaseAutoLoginMiddleware):
    def get_queryset(self):
        return User.objects.filter(kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER])

    def get_proconnect_authorize_url(self, user, next_url):
        return reverse(
            "pro_connect:authorize",
            query={"user_kind": user.kind, "next_url": next_url, "user_email": user.email},
        )

    def get_no_user_url(self, email, next_url):
        return reverse("signup:choose_user_kind", query={"next_url": next_url})


class DropDownMiddleware:
    TIMEOUT = 600  # seconds

    def __init__(self, get_response):
        self.get_response = get_response

    def is_nexus_user(self, user):
        return user.is_authenticated and user.is_active and user.kind in [UserKind.PRESCRIBER, UserKind.EMPLOYER]

    def __call__(self, request):
        cached_data = {}
        if self.is_nexus_user(request.user):
            cache_key = f"nexus_dropdown_status:{request.user.pk}"
            cached_data = cache.get(cache_key)

            if cached_data is None:
                cached_data = dropdown_status(user=request.user)
                cache.set(cache_key, cached_data, timeout=self.TIMEOUT)

        request.nexus_dropdown = cached_data
        return self.get_response(request)
