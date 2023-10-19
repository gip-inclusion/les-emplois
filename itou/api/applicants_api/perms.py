from rest_framework.permissions import IsAuthenticated

from itou.companies.models import SiaeMembership


class ApplicantsAPIPermission(IsAuthenticated):
    def has_permission(self, request, view) -> bool:
        """
        Check that user:
            - belongs to one SIAE only (dedicated API account)
            - is admin
        """
        if not super().has_permission(request, view):
            return False

        memberships = request.user.active_or_in_grace_period_siae_memberships()

        try:
            return memberships.get().is_admin
        except (SiaeMembership.DoesNotExist, SiaeMembership.MultipleObjectsReturned):
            return False
