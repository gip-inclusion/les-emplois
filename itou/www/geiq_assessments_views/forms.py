from django import forms
from django.forms import widgets

from itou.files.forms import ItouFileField
from itou.geiq_assessments.models import Assessment
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.utils.constants import MB


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
        label="Sélectionnez la DDETS",
        queryset=Institution.objects.filter(kind=InstitutionKind.DDETS_GEIQ).order_by("department"),
        required=False,
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
        label="Sélectionnez la DREETS",
        queryset=Institution.objects.filter(kind=InstitutionKind.DREETS_GEIQ).order_by("name"),
        required=False,
    )

    def __init__(self, *args, geiq_name, antenna_names, **kwargs):
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
        for antenna_id, antenna_name in antenna_names.items():
            if antenna_id:  # Ignore main geiq with id 0
                field_name = self.get_antenna_field(antenna_id)
                self.fields[field_name] = forms.BooleanField(label=antenna_name, required=False)
                antenna_fields.append(field_name)
        self.antenna_fields = antenna_fields

    def get_antenna_field(self, antenna_id):
        return f"{self.ANTENNA_PREFIX}_{antenna_id}"

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


class ActionFinancialAssessmentForm(forms.Form):
    assessment_file = ItouFileField(content_type="application/pdf", max_upload_size=5 * MB, label="Bilan")


class GeiqCommentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ["geiq_comment"]
        labels = {
            "geiq_comment": "Renseignez un commentaire",
        }
