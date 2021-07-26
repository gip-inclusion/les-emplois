from rest_framework.permissions import IsAuthenticated


class SiaeAPIPermission(IsAuthenticated):
    def has_permission(self, request, view):
        """
        Pole Emploi permission:
         - user must be authenticated
         - user must be using a PE-approved account
        """
        # Check whether user has done "basic" platform identification
        is_authenticated = super().has_permission(request, view)

        if not is_authenticated:
            # No need to go further => 403
            return False

        return True
