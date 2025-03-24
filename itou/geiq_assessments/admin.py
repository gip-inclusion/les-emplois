import logging
from pprint import pformat

from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured
from django.utils.html import format_html

from itou.geiq import sync
from itou.geiq_assessments import models
from itou.utils.admin import (
    ItouModelAdmin,
    PkSupportRemarkInline,
    ReadonlyMixin,
    get_admin_view_link,
)
from itou.utils.apis import geiq_label


logger = logging.getLogger(__name__)


@admin.register(models.AssessmentCampaign)
class AssessmentCampaignAdmin(ItouModelAdmin):
    @admin.action(description="Récupérer & stocker la liste des GEIQ avec leurs antennes")
    def download_label_infos(self, request, queryset):
        for campaign in queryset.select_related("label_infos"):
            if hasattr(campaign, "label_infos"):
                messages.error(request, f"Les informations LABEL de la campagne {campaign} ont déjà été récupérées.")
                continue

            try:
                data = sync.get_geiq_infos()
                campaign.label_infos = models.LABELInfos.objects.create(campaign=campaign, data=data)
            except ImproperlyConfigured:
                messages.error(request, "Synchronisation impossible avec Label: configuration incomplète")
                return

            except geiq_label.LabelAPIError:
                logger.warning("Error while syncing GEIQ campaign %s with Label", campaign)

                messages.error(request, f"Erreur lors de la synchronisation de la campagne {campaign} avec Label")

            else:
                messages.success(request, f"Les informations LABEL de la campagne {campaign} ont été récupérées.")

    actions = [download_label_infos]
    fields = [
        "year",
        "submission_deadline",
        "review_deadline",
        "label_infos_link",
    ]
    readonly_fields = ("label_infos_link",)
    list_display = (
        "pk",
        "year",
        "submission_deadline",
        "review_deadline",
    )
    inlines = [
        PkSupportRemarkInline,
    ]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("year",)
        return self.readonly_fields

    @admin.display(description="données LABEL")
    def label_infos_link(self, obj):
        return (
            get_admin_view_link(obj.label_infos, content=obj.label_infos.synced_at.isoformat())
            if hasattr(obj, "label_infos")
            else None
        )


@admin.register(models.LABELInfos)
class LABELInfosAdmin(ReadonlyMixin, ItouModelAdmin):
    fields = ["campaign", "synced_at", "pretty_data"]

    @admin.display(description="Données LABEL")
    def pretty_data(self, obj):
        if obj.data:
            return format_html("<pre><code>{}</code></pre>", pformat(obj.data, width=200))

        return "-"
