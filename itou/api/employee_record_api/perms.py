from rest_framework.permissions import IsAuthenticated


# Custom permission handler for employee record API


class EmployeeRecordAPIPermission(IsAuthenticated):
    """
    Custom manager handler for employee record API

    Ensures that connected user is at least member of one SIAE
    If this SIAE is not eligible to employee record, the API will return no result.
    A more defensive approach (check each SIAE) can be implemented at the view/viewset level.
    """

    # Technical note:
    # when using the browseable API (dev context), permissions are check twice
    # - once for JSON rendering (real world use case)
    # - once for HTML rendering
    # This is normal, and permission checking only occurs once in production.

    def has_permission(self, request, view):
        """
        Check permissions on the "list" level (when fetching a list of results)

        Note that there is no need here to implement permissions
        to the "instance" or object level (fetching a single employee record by ID):
        list level permissions are checked every time if `has_object_permission` is not implemented
        """
        # Check whether user has done "basic" platform identification
        is_authenticated = super().has_permission(request, view)

        if not is_authenticated:
            # No need to go further => 403
            return False

        # Now that we know that user is authenticated,
        # we must assert they are:
        # - members of one or more active SIAE
        # - admin
        # If a SIAE is not eligible, there will be no result available (defensive enough)
        has_memberships = (
            request.user.company_set.filter(siaemembership__is_active=True, siaemembership__is_admin=True)
            .active_or_in_grace_period()
            .exists()
        )

        # OK or 403
        return has_memberships
