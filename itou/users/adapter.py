from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.urls import reverse


class UserAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        url = reverse("dashboard:index")

        # In demo, false accounts are used by many different persons but never recreated.
        # The welcoming tour should show up anyway.
        if not request.user.has_completed_welcoming_tour or settings.ITOU_ENVIRONMENT == "REVIEW_APP":
            # TODO: replace environment by DEMO after review
            url = reverse("welcoming_tour:index")
        return url
