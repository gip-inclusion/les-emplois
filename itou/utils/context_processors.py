from urllib.parse import urlencode

from itou.communications.cache import get_cached_active_announcement


def matomo(request):
    context = {}
    url = request.path
    if request.resolver_match:
        url = request.resolver_match.route
    # Only keep Matomo-related params for now.
    params = {k: v for k, v in request.GET.lists() if k.startswith(("utm_", "mtm_", "piwik_"))}
    if params:
        url = f"{url}?{urlencode(sorted(params.items()), doseq=True)}"
    context["matomo_custom_url"] = url
    context["matomo_user_id"] = getattr(request.user, "pk", None)
    return context


def active_announcement_campaign(request):
    campaign = get_cached_active_announcement()

    return {
        "active_campaign_announce": (campaign if campaign is not None and campaign.items.count() else None),
        "active_campaign_announce_items": campaign.items_for_template(
            request.user.kind if request.user.is_authenticated else None
        )
        if campaign is not None
        else [],
    }
