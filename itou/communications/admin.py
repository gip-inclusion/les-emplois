from django.contrib import admin

from itou.communications import models
from itou.utils.admin import ItouModelAdmin, ItouTabularInline


class AnnouncementItemInline(ItouTabularInline):
    model = models.AnnouncementItem
    fields = ("priority", "title", "description")
    extra = 0


@admin.register(models.AnnouncementCampaign)
class AnnouncementCampaignAdmin(ItouModelAdmin):
    list_display = ("start_date", "end_date", "live")
    fields = ("max_items", "start_date", "live")
    inlines = (AnnouncementItemInline,)
