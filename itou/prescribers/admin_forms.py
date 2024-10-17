from django import forms

from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization


class PrescriberOrganizationAdminForm(forms.ModelForm):
    class Meta:
        model = PrescriberOrganization
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("kind") == PrescriberOrganizationKind.OTHER
            and self.instance.authorization_status == PrescriberAuthorizationStatus.VALIDATED
        ):
            raise forms.ValidationError(
                "Cette organisation a été habilitée. Vous devez sélectionner un type différent de “Autre”."
            )
        return cleaned_data
