from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from itou.users.enums import IdentityProvider, UserKind
from itou.utils import constants as global_constants
from itou.www.login import urls as login_urls


def extract_membership_infos_and_update_session(memberships, org_through_field, session):
    current_org_pk = session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
    orgs = []
    current_org = None
    admin_status = {}
    for membership in memberships:
        org = getattr(membership, org_through_field)
        orgs.append(org)
        if org.pk == current_org_pk:
            current_org = org
        admin_status[org.pk] = membership.is_admin
    if current_org is None:
        if orgs:
            # If an org exists, choose the first one
            current_org = orgs[0]
            session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = current_org.pk
        elif current_org_pk:
            # If the user has not active membership anymore
            # => No need to track the current org in session (none)
            # => Remove any old session entry if needed
            del session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY]
    return (
        sorted(orgs, key=lambda o: (o.kind, o.display_name)),
        current_org,
        current_org and admin_status[current_org.pk],
    )


class ItouCurrentOrganizationMiddleware:
    """
    Store the ID of the current prescriber organization or employer structure in session
    and enrich the request object with the memberships infos.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user

        redirect_message = None
        if user.is_authenticated:
            if user.is_siae_staff:
                active_memberships = list(user.siaemembership_set.filter(is_active=True).order_by("created_at"))
                siaes = {
                    siae.pk: siae
                    for siae in user.siae_set.filter(
                        pk__in=[membership.siae_id for membership in active_memberships]
                    ).active_or_in_grace_period()
                }
                really_active_memberships = []
                for membership in active_memberships:
                    if membership.siae_id in siaes:
                        # The siae is active (or in grace period)
                        membership.siae = siaes[membership.siae_id]
                        really_active_memberships.append(membership)
                # If there is no current siae, we want to default to the first active one
                # (and preferably not one in grace period)
                really_active_memberships.sort(key=lambda m: m.siae.has_convention_in_grace_period)

                (
                    request.organizations,
                    request.current_organization,
                    request.is_current_organization_admin,
                ) = extract_membership_infos_and_update_session(
                    really_active_memberships,
                    "siae",
                    request.session,
                )

                if not request.current_organization:
                    # SIAE user has no active SIAE and thus must not be able to access any page,
                    # thus we force a logout with a few exceptions (cf skip_middleware_conditions)
                    if not active_memberships:
                        redirect_message = format_html(
                            "Nous sommes désolés, votre compte n'est "
                            "actuellement rattaché à aucune structure.<br>"
                            "Nous espérons cependant avoir l'occasion de vous accueillir de "
                            "nouveau."
                        )
                    else:
                        redirect_message = (
                            "Nous sommes désolés, votre compte n'est "
                            "malheureusement plus actif car la ou les "
                            "structures associées ne sont plus "
                            "conventionnées. Nous espérons cependant "
                            "avoir l'occasion de vous accueillir de "
                            "nouveau."
                        )

            elif user.is_prescriber:
                (
                    request.organizations,
                    request.current_organization,
                    request.is_current_organization_admin,
                ) = extract_membership_infos_and_update_session(
                    user.prescribermembership_set.filter(is_active=True)
                    .order_by("created_at")
                    .select_related("organization"),
                    "organization",
                    request.session,
                )

            elif user.is_labor_inspector:
                (
                    request.organizations,
                    request.current_organization,
                    request.is_current_organization_admin,
                ) = extract_membership_infos_and_update_session(
                    user.institutionmembership_set.filter(is_active=True)
                    .order_by("created_at")
                    .select_related("institution"),
                    "institution",
                    request.session,
                )
                if not request.current_organization:
                    redirect_message = format_html(
                        "Nous sommes désolés, votre compte n'est "
                        "actuellement rattaché à aucune structure.<br>"
                        "Nous espérons cependant avoir l'occasion de vous accueillir de "
                        "nouveau."
                    )

        # Accepting an invitation to join a group is a two-step process.
        # - View one: account creation or login.
        # - View two: user is added to the group.
        # In view two, the user is authenticated but he does not belong to any group.
        # This raises an error so we skip the middleware only in this case.
        login_routes = [reverse(f"login:{url.name}") for url in login_urls.urlpatterns] + [reverse("account_login")]
        skip_middleware_conditions = [
            request.path in login_routes,
            request.path.startswith("/invitations/") and not request.path.startswith("/invitations/invite"),
            request.path.startswith("/signup/siae/join"),  # siae staff about to join an siae
            request.path.startswith("/signup/facilitator/join"),  # facilitator about to join an siae
            request.path == reverse("account_logout"),
            request.path.startswith("/hijack/release"),  # Allow to release hijack
        ]
        if any(skip_middleware_conditions):
            return self.get_response(request)

        # Force Inclusion Connect
        if (
            user.is_authenticated
            and user.identity_provider != IdentityProvider.INCLUSION_CONNECT
            and user.kind in [UserKind.PRESCRIBER, UserKind.SIAE_STAFF]
            and not request.path.startswith("/dashboard/activate_ic_account")  # Allow to access ic activation view
            and not request.path.startswith("/inclusion_connect")  # Allow to access ic views
            and settings.FORCE_IC_LOGIN  # Allow to disable on dev setup
        ):
            # Add request.path as next param ?
            return HttpResponseRedirect(reverse("dashboard:activate_ic_account"))

        if redirect_message is not None:
            messages.warning(request, redirect_message)
            return redirect("account_logout")

        return self.get_response(request)
