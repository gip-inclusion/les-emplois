def can_view_stats(user):
    """
    Check if user has the `is_stats_vip` or the 'is_superuser' flag ("Pilotage" or God-mode).
    Used for access protection of Metabase dashboards.

    Usage:

    @user_passes_test(can_view_stats, login_url="/dashboard")
    def reporting(request, template_name=_STATS_HTML_TEMPLATE):
        ...
    """
    return user.is_stats_vip or user.is_superuser
