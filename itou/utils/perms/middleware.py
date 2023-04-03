from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import safestring

from itou.users.enums import IdentityProvider, UserKind
from itou.utils import constants as global_constants
from itou.www.login import urls as login_urls


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

        # Accepting an invitation to join a group is a two-step process.
        # - View one: account creation or login.
        # - View two: user is added to the group.
        # In view two, the user is authenticated but he does not belong to any group.
        # This raises an error so we skip the middleware only in this case.
        login_routes = [reverse(f"login:{url.name}") for url in login_urls.urlpatterns] + [reverse("account_login")]
        skip_middleware_conditions = [
            request.path in [reverse("account_logout"), *login_routes],
            request.path.startswith("/invitations/") and not request.path.startswith("/invitations/invite"),
            request.path.startswith("/signup/siae/join"),  # siae staff about to join an siae
            request.path.startswith("/signup/facilitator/join"),  # facilitator about to join an siae
        ]
        if any(skip_middleware_conditions):
            return self.get_response(request)

        if user.is_authenticated:
            # FIXME(alaurent) move to a dedicated Middleware ?
            # Force Inclusion Connect
            if (
                user.identity_provider != IdentityProvider.INCLUSION_CONNECT
                and user.kind in [UserKind.PRESCRIBER, UserKind.SIAE_STAFF]
                and not request.path.startswith("/dashboard/activate_ic_account")  # Allow to access ic activation view
                and not request.path.startswith("/inclusion_connect")  # Allow to access ic views
            ):
                # Add request.path as next param ?
                return HttpResponseRedirect(reverse("dashboard:activate_ic_account"))

            if user.is_siae_staff:
                current_siae_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_SIAE_KEY)
                siae_set = user.siae_set.filter(siaemembership__is_active=True).active_or_in_grace_period()

                if not siae_set.filter(pk=current_siae_pk).exists():
                    # User is no longer an active member of siae stored in session,
                    # or siae stored in session no longer exists.
                    # Let's automatically switch to another siae when possible,
                    # preferably an active one.
                    first_siae = siae_set.active().first() or siae_set.first()
                    if first_siae:
                        request.session[global_constants.ITOU_SESSION_CURRENT_SIAE_KEY] = first_siae.pk
                    else:
                        # SIAE user has no active SIAE and thus must not be able to access any page,
                        # thus we force a logout with a few exceptions:
                        # - logout (to avoid infinite redirect loop)
                        # - pages of the invitation process (including login)
                        #   as being invited to a new active siae is the only
                        #   way for an inactive siae user to be ressucitated.
                        if not user.is_siae_staff_with_siae:
                            message = (
                                "Nous sommes désolés, votre compte n'est "
                                "actuellement rattaché à aucune structure.<br>"
                                "Nous espérons cependant avoir l'occasion de vous accueillir de "
                                "nouveau."
                            )
                        else:
                            message = (
                                "Nous sommes désolés, votre compte n'est "
                                "malheureusement plus actif car la ou les "
                                "structures associées ne sont plus "
                                "conventionnées. Nous espérons cependant "
                                "avoir l'occasion de vous accueillir de "
                                "nouveau."
                            )
                        message = safestring.mark_safe(message)
                        messages.warning(request, message)
                        return redirect("account_logout")

            elif user.is_prescriber:
                # Prescriber users can now select an organization
                # (if they are member of several prescriber organizations)
                current_prescriber_org_key = request.session.get(
                    global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY
                )
                if user.is_prescriber_with_org:
                    if not current_prescriber_org_key:
                        # Choose first prescriber organization for user if none is selected yet
                        # (f.i. after login)
                        request.session[global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = (
                            user.prescribermembership_set.filter(is_active=True).first().organization.pk
                        )
                elif current_prescriber_org_key:
                    # If the user is an "orienteur"
                    # => No need to track the current org in session (none)
                    # => Remove any old session entry if needed
                    del request.session[global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY]

            elif user.is_labor_inspector:
                current_institution_key = request.session.get(global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY)
                if not current_institution_key:
                    first_active_membership = user.institutionmembership_set.filter(is_active=True).first()
                    if not first_active_membership:
                        message = (
                            "Nous sommes désolés, votre compte n'est "
                            "actuellement rattaché à aucune structure.<br>"
                            "Nous espérons cependant avoir l'occasion de vous accueillir de "
                            "nouveau."
                        )
                        message = safestring.mark_safe(message)
                        messages.warning(request, message)
                        return redirect("account_logout")

                    request.session[
                        global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY
                    ] = first_active_membership.institution.pk

        response = self.get_response(request)

        # After the view is called.

        return response
