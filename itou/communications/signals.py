from itou.communications.cache import get_cached_active_announcement, update_active_announcement_cache


def update_cached_announcement_on_campaign_changes(sender, instance, *args, **kwargs):
    campaign = get_cached_active_announcement()
    if campaign is None or instance.pk == campaign.pk:
        update_active_announcement_cache()


def update_cached_announcement_on_item_changes(sender, instance, *args, **kwargs):
    campaign = get_cached_active_announcement()
    if campaign is None or instance.campaign == campaign:
        update_active_announcement_cache()
