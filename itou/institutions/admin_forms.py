from django import forms

from itou.institutions.models import Institution


class InstitutionAdminForm(forms.ModelForm):
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
        model = Institution
        fields = "__all__"
