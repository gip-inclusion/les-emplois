from django import forms

from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization


class PrescriberOrganizationAdminForm(forms.ModelForm):
    # Add a custom form field that is not part of the model in the admin.
    extra_field_refresh_geocoding = forms.BooleanField(
        label="Recalculer le geocoding",
        help_text=(
            "Si cette case est cochée, les coordonnées géographiques seront mises à "
            "jour si l'adresse est correctement renseignée."
        ),
        required=False,
    )

    class Meta:
        model = PrescriberOrganization
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("kind") == PrescriberOrganizationKind.OTHER
            and self.instance.is_authorized
            # TODO(calummackervoy): included to permit cleaning existing rows. We can later remove this
            and self.instance.kind != PrescriberOrganizationKind.OTHER
        ):
            raise forms.ValidationError(
                "Cette organisation a été habilitée. Vous devez sélectionner un type différent de “Autre”"
            )
