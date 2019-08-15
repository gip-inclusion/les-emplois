from django.core.exceptions import PermissionDenied


def perm_required(*roles):
    """
    Requires user membership in at least one of the perm passed in.

    Usage:
        @role_required('prescriber', 'siae_staff')
        @role_required('job_seeker')
    """

    def decorated(function):

        def wrapper(request, *args, **kwargs):
            perms = [getattr(request.user, f"is_{role}") for role in roles]
            if not (any(perms) or request.user.is_superuser):
                raise PermissionDenied  # Raise a 403.
            return function(request, *args, **kwargs)

        return wrapper

    return decorated
