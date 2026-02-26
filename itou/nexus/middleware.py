from django.conf import settings
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
    def __init__(self, get_response):
        self.get_response = get_response

    def must_load_dropdown(self, request):
        return (
            settings.NEXUS_DROPDOWN_ENABLED
            and not request.path.startswith("/portal")
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.kind in [UserKind.PRESCRIBER, UserKind.EMPLOYER]
        )

    def __call__(self, request):
        request.nexus_dropdown = {}
        if self.must_load_dropdown(request):
            request.nexus_dropdown = dropdown_status(user=request.user)
        return self.get_response(request)
