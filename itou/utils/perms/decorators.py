# The wild bunch of usefull decorators


def can_view_stats_vip(user):
    """
    Used for access protection of Metabase dashboards.
    """
    return user.can_view_stats_vip
