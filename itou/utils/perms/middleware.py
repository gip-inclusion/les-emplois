from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.urls import reverse
from django_otp import user_has_device
from itoutils.urls import add_url_params

from itou.companies.models import Company, CompanyMembership
from itou.institutions.models import Institution, InstitutionMembership
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import IdentityProvider, UserKind
from itou.utils import constants as global_constants
from itou.www.logout.enums import LogoutWarning


def extract_membership_infos_and_update_session(
    company_memberships,
    prescriber_memberships,
    institution_memberships,
    session,
):
    current_org_key = session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)

    orgs = []
    current_org = None
    admin_status = {}
    for membership in company_memberships + prescriber_memberships + institution_memberships:
        org = membership.get_organization()
        orgs.append(org)
        if org.organization_switch_key == current_org_key:
            current_org = org
        admin_status[org.organization_switch_key] = membership.is_admin
    if current_org is None:
        if orgs:
            # If an org exists, choose the first one
            current_org = orgs[0]
            session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = current_org.organization_switch_key
        elif current_org_key:
            # If the user has not active membership anymore
            # => No need to track the current org in session (none)
            # => Remove any old session entry if needed
            del session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY]
    return (
        sorted(orgs, key=lambda o: (o.kind, o.display_name)),
        current_org,
        current_org and admin_status[current_org.organization_switch_key],
    )


def get_active_company_memberships(user):
    # Do not use the default manager to avoid double checking whether the user is_active.
    # The AuthenticationMiddleware already checked that the user is_active.
    memberships = list(CompanyMembership.include_inactive.filter(user=user, is_active=True))
    companies = {
        company.pk: company
        for company in user.company_set.filter(pk__in=[membership.company_id for membership in memberships])
        .active_or_in_grace_period()
        .select_related("convention")
    }
    active_memberships = []
    for membership in memberships:
        if membership.company_id in companies:
            # The company is active (or in grace period)
            membership.company = companies[membership.company_id]
            active_memberships.append(membership)
    # If there is no current company, we want to default to the first active one
    # (and preferably not one in grace period)
    active_memberships.sort(key=lambda m: (m.company.has_convention_in_grace_period, m.joined_at))
    return active_memberships


def get_active_prescriber_memberships(user):
    # Do not use the default manager to avoid double checking whether the user is_active.
    # The AuthenticationMiddleware already checked that the user is_active.
    return list(
        PrescriberMembership.include_inactive.filter(user=user, is_active=True)
        .order_by("joined_at")
        .select_related("organization")
    )


def get_active_institution_memberships(user):
    # Do not use the default manager to avoid double checking whether the user is_active.
    # The AuthenticationMiddleware already checked that the user is_active.
    return list(
        InstitutionMembership.include_inactive.filter(user=user, is_active=True)
        .order_by("joined_at")
        .select_related("institution")
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

        logout_warning = None
        request.from_employer = False
        request.from_prescriber = False
        request.from_authorized_prescriber = False
        request.from_institution = False
        if user.is_authenticated and user.is_professional:
            company_memberships = get_active_company_memberships(user)
            prescriber_memberships = get_active_prescriber_memberships(user)
            institution_memberships = get_active_institution_memberships(user)

            (
                request.organizations,
                request.current_organization,
                request.is_current_organization_admin,
            ) = extract_membership_infos_and_update_session(
                company_memberships,
                prescriber_memberships,
                institution_memberships,
                request.session,
            )

            # FT users must have at least one FT organization
            if user.email.endswith(global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX) and not any(
                m.organization.kind == PrescriberOrganizationKind.FT for m in prescriber_memberships
            ):
                logout_warning = LogoutWarning.FT_NO_FT_ORGANIZATION
            elif not request.current_organization:
                logout_warning = LogoutWarning.NO_ORGANIZATION

            else:
                if isinstance(request.current_organization, PrescriberOrganization):
                    request.from_prescriber = True
                    if request.current_organization.is_authorized:
                        request.from_authorized_prescriber = True
                elif isinstance(request.current_organization, Company):
                    request.from_employer = True
                elif isinstance(request.current_organization, Institution):
                    request.from_institution = True

        # Accepting an invitation to join a group is a two-step process.
        # - View one: account creation or login.
        # - View two: user is added to the group.
        # In view two, the user is authenticated but he does not belong to any group.
        # This raises an error so we skip the middleware only in this case.
        skip_middleware_conditions = [
            request.path.startswith("/login/"),
            request.path.startswith("/logout/"),
            request.path.startswith("/invitations/") and not request.path.startswith("/invitations/invite"),
            request.path.startswith("/signup/siae/join"),  # employer about to join a company
            request.path.startswith("/signup/facilitator/join"),  # facilitator about to join a company
            request.path.startswith("/signup/prescriber/join"),  # prescriber about to join a organization
            request.path in [reverse("account_login"), reverse("account_logout")],
            request.path.startswith("/hijack/release"),  # Allow to release hijack
            request.path.startswith("/api"),  # APIs should handle those errors
        ]
        if any(skip_middleware_conditions):
            return self.get_response(request)

        # Force ProConnect
        if (
            user.is_authenticated
            and user.identity_provider != IdentityProvider.PRO_CONNECT
            and (request.from_employer or request.from_prescriber)
            and not request.path.startswith(
                "/dashboard/activate-pro-connect-account"
            )  # Allow to access ic activation view
            and not request.path.startswith("/pro_connect")  # Allow to access ProConnect views
            and settings.FORCE_PROCONNECT_LOGIN  # Allow to disable on dev setup
        ):
            # Add request.path as next param ?
            return HttpResponseRedirect(reverse("dashboard:activate_pro_connect_account"))

        # Log staff users in dedicated login page
        if not user.is_authenticated and request.path.startswith("/admin"):
            return HttpResponseRedirect(
                reverse("login:itou_staff", query={REDIRECT_FIELD_NAME: request.get_full_path()})
            )

        # Nexus : Whitelist for Nexus views
        # FIXME: Remove once we merge prescribers and employers
        if (
            user.is_authenticated
            and user.is_professional
            and any(
                [
                    request.path.startswith("/portal"),
                    request.path.startswith("/signup/siae/select"),
                ]
            )
        ):
            return self.get_response(request)

        # Force OTP for staff users
        if (
            settings.REQUIRE_OTP_FOR_STAFF
            and user.is_authenticated
            and user.kind == UserKind.ITOU_STAFF
            and not user.is_verified()
        ):
            login_verify_otp_url = reverse("login:verify_otp")
            if user_has_device(user) and request.path != login_verify_otp_url:
                return HttpResponseRedirect(
                    add_url_params(login_verify_otp_url, {REDIRECT_FIELD_NAME: request.get_full_path()})
                )
            if not request.path.startswith("/staff/otp"):
                return HttpResponseRedirect(reverse("itou_staff_views:otp_devices"))

        if logout_warning is not None:
            return HttpResponseRedirect(reverse("logout:warning", kwargs={"kind": logout_warning}))

        return self.get_response(request)
