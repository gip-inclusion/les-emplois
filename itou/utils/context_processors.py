from urllib.parse import urlencode

from django.conf import settings

from itou.communications.cache import get_cached_active_announcement


def matomo(request):
    if not request.resolver_match:
        return {"send_to_matomo": False}

    context = {"send_to_matomo": True}
    url = request.resolver_match.route
    # Only keep Matomo-related params for now.
    params = {k: v for k, v in request.GET.lists() if k.startswith(("utm_", "mtm_", "piwik_"))}
    if params:
        url = f"{url}?{urlencode(sorted(params.items()), doseq=True)}"
    context["matomo_custom_url"] = url
    context["matomo_user_id"] = getattr(request.user, "pk", None)
    return context


def automatic_modals(request):
    user = request.user
    context = {
        "display_campaign_announce": False,
        "display_new_url_redirect_modal": False,
    }

    if (
        settings.REDIRECT_TO_NEW_URL
        and request.get_host() != settings.NEW_DOMAIN
        and user.is_authenticated
        and user.is_itou_staff
    ):
        context["display_new_url_redirect_modal"] = True
        return context

    if user and user.is_authenticated and not request.path.startswith("/otp/verify"):
        if campaign := get_cached_active_announcement():
            context["display_campaign_announce"] = True
            context["active_campaign_announce"] = campaign
            context["active_campaign_announce_items"] = campaign.items_for_template(user.kind)
            return context

    return context
