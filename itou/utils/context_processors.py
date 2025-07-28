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
    if request.user and request.user.is_authenticated:
        if campaign := get_cached_active_announcement():
            return {
                "display_campaign_announce": True,
                "active_campaign_announce": campaign,
                "active_campaign_announce_items": campaign.items_for_template(request.user.kind),
            }

    return {"display_campaign_announce": False}
