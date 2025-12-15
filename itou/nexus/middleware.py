from django.urls import reverse
from itoutils.django.nexus.middleware import BaseAutoLoginMiddleware

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
