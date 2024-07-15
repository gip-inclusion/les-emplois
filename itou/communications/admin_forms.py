from django import forms
from django.core.exceptions import ValidationError

from itou.communications.models import AnnouncementCampaign


class AnnouncementCampaignAdminForm(forms.ModelForm):
    class Meta:
        model = AnnouncementCampaign
        fields = "__all__"

    def prevent_concurrent_campaigns(self):
        start_date = self.cleaned_data.get("start_date")
        end_date = self.cleaned_data.get("end_date")

        if start_date > end_date:
            raise ValidationError("Impossible de finir la campagne avant qu'elle ne commence.")

        existing_campaign = (
            AnnouncementCampaign.objects.filter(start_date__gte=start_date, end_date__lte=end_date)
            .exclude(pk=self.instance.pk)
            .first()
        )
        if existing_campaign is not None:
            raise ValidationError(
                "Il y a déjà une campagne entre ces dates "
                f"({ existing_campaign.start_date } à { existing_campaign.end_date })"
            )

    def clean_max_items(self):
        max_items = self.cleaned_data.get("max_items")

        if max_items < 1:
            raise ValidationError("Impossible de lancer une campagne sans articles.")

        return max_items

    def clean(self):
        super().clean()
        self.prevent_concurrent_campaigns()
