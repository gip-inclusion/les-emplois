from datetime import date, datetime

from django.core.cache import cache

from itou.communications.models import AnnouncementCampaign


CACHE_ACTIVE_ANNOUNCEMENT_CAMPAIGN_KEY = "active-announcement-campaign"


def update_active_announcement_cache():
    today = date.today()

    campaign = (
        AnnouncementCampaign.objects.filter(start_date__lte=today, end_date__gt=today)
        .prefetch_related("items")
        .first()
    )

    if campaign is None:
        cache.set(CACHE_ACTIVE_ANNOUNCEMENT_CAMPAIGN_KEY, {"value": None}, None)
        return None

    seconds_until_end = (datetime.combine(campaign.end_date, datetime.min.time()) - datetime.now()).total_seconds()
    cache.set(CACHE_ACTIVE_ANNOUNCEMENT_CAMPAIGN_KEY, {"value": campaign}, seconds_until_end)
    return campaign
