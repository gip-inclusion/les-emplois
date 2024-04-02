from rest_framework.permissions import IsAuthenticated


class ApplicantsAPIPermission(IsAuthenticated):
    def has_permission(self, request, view) -> bool:
        """
        Check that user is admin of every companies he belongs to.
        """
        if not super().has_permission(request, view):
            return False

        if not request.user.is_employer:
            return False

        memberships_status_is_admin = request.user.active_or_in_grace_period_company_memberships().values_list(
            "is_admin", flat=True
        )
        return memberships_status_is_admin and all(memberships_status_is_admin)
