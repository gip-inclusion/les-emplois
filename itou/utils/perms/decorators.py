# The wild bunch of usefull decorators


def can_view_stats(user):
    """
    Check if user has the `is_stats_vip` flag ("Pilotage")
    Used for access protection of Metabase dashboards
    """
    return user.is_stats_vip
