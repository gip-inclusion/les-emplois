from django.contrib import admin

from itou.communications.forms import AnnouncementItemForm
from itou.communications.models import AnnouncementCampaign, AnnouncementItem
from itou.utils.admin import ItouModelAdmin, ItouStackedInline


class AnnouncementItemInline(ItouStackedInline):
    model = AnnouncementItem
    form = AnnouncementItemForm
    extra = 0


@admin.register(AnnouncementCampaign)
class AnnouncementCampaignAdmin(ItouModelAdmin):
    list_display = ("start_date", "end_date", "live")
    fields = ("max_items", "start_date", "live")
    inlines = (AnnouncementItemInline,)
