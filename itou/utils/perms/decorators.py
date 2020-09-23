# The wild bunch of usefull decorators


def can_view_stats(user):
    """
    Check if user has the `is_stats_vip` or the 'is_superuser' flag ("Pilotage" or God-mode).
    Used for access protection of Metabase dashboards.
    """
    return user.is_stats_vip or user.is_superuser
