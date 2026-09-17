def get_org_admins(organizations, user=None):
    """This function excludes the given user from its org admins if given.

    Returns a dict of User: Organization.

    The organizations param should be taken from `request.organizations`, so:

        get_org_admins(getattr(request, 'organizations', None), request.user)

    should be what you need.
    """
    admins = {}
    if organizations:
        for organization in organizations:
            org_admins_memberships = organization.memberships.filter(is_admin=True)
            for admin_membership in org_admins_memberships:
                if admin_membership.user != user:
                    admins[admin_membership.user] = organization
    return admins
