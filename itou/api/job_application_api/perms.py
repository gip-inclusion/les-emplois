from rest_framework.permissions import IsAuthenticated

from itou.api.auth import ServiceAccount
from itou.api.models import DepartmentToken


class JobApplicationSearchAPIPermission(IsAuthenticated):
    def has_permission(self, request, view) -> bool:
        """
        Check that user is actually a Department using its own token.
        """
        if not super().has_permission(request, view):
            return False

        return isinstance(request.user, ServiceAccount) and isinstance(request.auth, DepartmentToken)
