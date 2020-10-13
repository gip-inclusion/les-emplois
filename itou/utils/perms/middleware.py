from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import safestring
from django.utils.translation import gettext as _


class ItouCurrentOrganizationMiddleware:
    """
    Store the ID of the current prescriber organization or employer structure in session.
    https://docs.djangoproject.com/en/dev/topics/http/middleware/#writing-your-own-middleware
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Before the view is called.

        user = request.user

        if user.is_authenticated:

            if user.is_siae_staff:
                current_siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
                siae_set = user.siae_set.active_or_in_grace_period()
                if not siae_set.filter(pk=current_siae_pk).exists():
                    first_active_siae = siae_set.first()
                    if first_active_siae:
                        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = first_active_siae.pk
                    elif request.path not in [
                        reverse("account_logout"),
                        reverse("account_login"),
                    ] and not request.path.startswith("/invitations/"):
                        # SIAE user has no active SIAE and thus must not be able to access any page,
                        # thus we force a logout with a few exceptions:
                        # - logout (to avoid infinite redirect loop)
                        # - pages of the invitation process (including login)
                        #   as being invited to a new active siae is the only
                        #   way for an inactive siae user to be ressucitated.
                        message = (
                            "Nous sommes désolés, votre compte n'est "
                            "malheureusement plus actif car la ou les "
                            "structures associées ne sont plus "
                            "conventionnées. Nous espérons cependant "
                            "avoir l'occasion de vous accueillir de "
                            "nouveau sur la Plateforme."
                        )
                        message = safestring.mark_safe(message)
                        messages.warning(request, _(message))
                        return redirect("account_logout")

            elif user.is_prescriber:
                # Prescriber users can now select an organization from their dashboard
                # (if they are member of several prescriber organizations)
                if user.prescriberorganization_set.exists():
                    # Choose first prescriber organization for user if none is selected yet
                    # (f.i. after login)
                    request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = (
                        request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
                        or user.prescriberorganization_set.first().pk
                    )
                elif request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY):
                    # If the user is an "orienteur"
                    # => No need to track the current org in session (none)
                    # => Remove any old session entry if needed
                    del request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY]

        response = self.get_response(request)

        # After the view is called.

        return response
