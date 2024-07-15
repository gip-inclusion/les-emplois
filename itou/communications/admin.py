from django.contrib import admin

from itou.communications import models
from itou.communications.forms import AnnouncementItemForm
from itou.utils.admin import ItouModelAdmin, ItouStackedInline


class AnnouncementItemInline(ItouStackedInline):
    model = models.AnnouncementItem
    form = AnnouncementItemForm
    extra = 0


@admin.register(models.AnnouncementCampaign)
class AnnouncementCampaignAdmin(ItouModelAdmin):
    class Media:
        css = {"all": ("css/itou-admin.css",)}

    list_display = ("start_date", "end_date", "live")
    fields = ("max_items", "start_date", "live")
    inlines = (AnnouncementItemInline,)
