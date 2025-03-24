from django import forms
from django.forms import widgets

from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution


class CreateForm(forms.Form):
    ANTENNA_PREFIX = "antenna"
    main_geiq = forms.BooleanField(required=False)

    convention_with_ddets = forms.BooleanField(
        label="DDETS (Département)",
        widget=widgets.CheckboxInput(
            attrs={
                "aria-expanded": "false",
                "aria-controls": "id_ddets",
                "data-bs-target": ".ddets_group",
                "data-bs-toggle": "collapse",
            }
        ),
        required=False,
    )
    ddets = forms.ModelChoiceField(
        label="Département", queryset=Institution.objects.filter(kind=InstitutionKind.DDETS_GEIQ), required=False
    )
    convention_with_dreets = forms.BooleanField(
        label="DREETS (Région)",
        widget=widgets.CheckboxInput(
            attrs={
                "aria-expanded": "false",
                "aria-controls": "id_dreets",
                "data-bs-target": ".dreets_group",
                "data-bs-toggle": "collapse",
            }
        ),
        required=False,
    )
    dreets = forms.ModelChoiceField(
        label="Région", queryset=Institution.objects.filter(kind=InstitutionKind.DREETS_GEIQ), required=False
    )

    def __init__(self, *args, geiq_name, antennas, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ddets"].form_group_class = "form-group ms-4 collapse ddets_group"
        self.fields["dreets"].form_group_class = "form-group ms-4 collapse dreets_group"
        if self["convention_with_ddets"].value():
            # Make sure the collapse state is consistent
            self.fields["convention_with_ddets"].widget.attrs["aria-expanded"] = "true"
            self.fields["ddets"].form_group_class += " show"
        if self["convention_with_dreets"].value():
            # Make sure the collapse state is consistent
            self.fields["convention_with_dreets"].widget.attrs["aria-expanded"] = "true"
            self.fields["dreets"].form_group_class += " show"

        self.fields["main_geiq"].label = geiq_name

        antenna_fields = []
        for antenna in antennas:
            if antenna_id := antenna["id"]:  # Ignore main geiq with id 0
                field_name = f"{self.ANTENNA_PREFIX}_{antenna_id}"
                self.fields[field_name] = forms.BooleanField(label=antenna["nom"], required=False)
                antenna_fields.append(field_name)
        self.antenna_fields = antenna_fields

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("convention_with_ddets") and not cleaned_data.get("convention_with_dreets"):
            self.add_error(
                None,
                "Vous devez indiquer au moins une institution avec laquelle vous êtes conventionné.",
            )
        elif cleaned_data.get("convention_with_ddets") and not cleaned_data.get("ddets"):
            self.add_error(
                "ddets",
                "Ce champs est obligatoire.",
            )
        elif cleaned_data.get("convention_with_dreets") and not cleaned_data.get("dreets"):
            self.add_error(
                "dreets",
                "Ce champs est obligatoire.",
            )

        if not any(cleaned_data.get(field) for field in ["main_geiq"] + self.antenna_fields):
            self.add_error(
                None,
                "Vous devez choisir au moins une structure concernée par cette convention.",
            )
