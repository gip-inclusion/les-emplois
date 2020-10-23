from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from itou.siaes.models import Siae


def get_current_siae_or_404(request):
    pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
    queryset = Siae.objects.member_required(request.user)
    siae = get_object_or_404(queryset, pk=pk)
    return siae


def require_current_siae():
    """
    Ensure there is a current_siae and preload it, otherwise throw a 404.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            current_siae = get_current_siae_or_404(request)
            return view_func(request, current_siae=current_siae, *args, **kwargs)

        return _wrapped_view

    return decorator


def require_current_siae_is_active():
    """
    Ensure current_siae is active and preload it, otherwise throw a 404.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            current_siae = get_current_siae_or_404(request)
            if not current_siae.is_active:
                raise Http404
            return view_func(request, current_siae=current_siae, *args, **kwargs)

        return _wrapped_view

    return decorator


def require_current_siae_is_active_or_in_grace_period():
    """
    Ensure current_siae is active or in grace period, preload it,
    otherwise throw a 404.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            current_siae = get_current_siae_or_404(request)
            if not current_siae.is_active_or_in_grace_period:
                raise Http404
            return view_func(request, current_siae=current_siae, *args, **kwargs)

        return _wrapped_view

    return decorator


def require_siae_admin():
    """
    Ensure the user is admin of its current_siae.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            try:
                current_siae = get_current_siae_or_404(request)
            except Http404:
                raise PermissionDenied
            if not current_siae.has_admin(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
