from django import forms
from django.forms import widgets

from itou.files.forms import ItouFileField
from itou.geiq_assessments.models import Assessment
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.utils.constants import MB
from itou.utils.templatetags.format_filters import format_int_euros


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

    def __init__(self, *args, geiq_name, antenna_names, existing_antenna_ids, **kwargs):
        super().__init__(*args, **kwargs)
        self.antenna_names = antenna_names
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
        self.fields["main_geiq"].disabled = 0 in existing_antenna_ids

        antenna_fields = []
        for antenna_id, antenna_name in antenna_names.items():
            if antenna_id:  # Ignore main geiq with id 0
                field_name = self.get_antenna_field(antenna_id)
                self.fields[field_name] = forms.BooleanField(
                    label=antenna_name, required=False, disabled=antenna_id in existing_antenna_ids
                )
                antenna_fields.append(field_name)
        self.antenna_fields = antenna_fields

    def get_antenna_field(self, antenna_id):
        return f"{self.ANTENNA_PREFIX}_{antenna_id}"

    def iter_antenna_field(self):
        for field in self:
            if self.ANTENNA_PREFIX in field.name:
                yield field

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

    def conflicting_antennas(self):
        # Detect data sent for disabled fields which likely implies a concurrent creation
        if not self.data:
            return []
        conflicting_antennas = []
        if self.fields["main_geiq"].disabled and self.data.get("main_geiq"):
            conflicting_antennas.append({"id": 0, "name": self.fields["main_geiq"].label})

        for field_name in self.antenna_fields:
            field = self.fields[field_name]
            if field.disabled and self.data.get(field_name):
                for antenna_id, antenna_name in self.antenna_names.items():
                    if field_name == self.get_antenna_field(antenna_id):
                        conflicting_antennas.append({"id": antenna_id, "name": antenna_name})
        return conflicting_antennas


class ActionFinancialAssessmentForm(forms.Form):
    assessment_file = ItouFileField(content_type="application/pdf", max_upload_size=5 * MB, label="Bilan")


class GeiqCommentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ["geiq_comment"]
        labels = {
            "geiq_comment": "Renseignez un commentaire",
        }


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = [
            "review_comment",
            "convention_amount",
            "granted_amount",
            "advance_amount",
        ]
        labels = {
            "review_comment": "Commentaire",
        }

    advance_amount = forms.CharField(
        label="Premier versement déjà réalisé",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9 ]+"}),
    )
    convention_amount = forms.CharField(
        label="Montant conventionné (convention initiale + avenants)",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9 ]+"}),
    )
    granted_amount = forms.CharField(
        label="Montant total accordé",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9 ]+"}),
    )

    balance_amount = forms.CharField(label="Deuxième versement à prévoir", required=False, disabled=True)
    refund_amount = forms.CharField(label="Remboursement attendu", required=False, disabled=True)

    def __init__(self, *args, instance, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        self.fields["review_comment"].required = True
        if instance.reviewed_at:
            for field in self.fields.values():
                field.disabled = True
            for field in ["advance_amount", "convention_amount", "granted_amount"]:
                self.initial[field] = format_int_euros(getattr(instance, field))

    def _clean_int_amount(self, field):
        amount = self.cleaned_data[field].replace(" ", "")
        try:
            return int(amount)
        except ValueError:
            raise forms.ValidationError("Vous devez renseigner un nombre entier")

    def clean_advance_amount(self):
        return self._clean_int_amount("advance_amount")

    def clean_convention_amount(self):
        return self._clean_int_amount("convention_amount")

    def clean_granted_amount(self):
        return self._clean_int_amount("granted_amount")

    def clean(self):
        super().clean()
        if (convention_amount := self.cleaned_data.get("convention_amount")) is not None:
            if (
                granted_amount := self.cleaned_data.get("granted_amount")
            ) is not None and granted_amount > convention_amount:
                self.add_error(
                    "granted_amount",
                    forms.ValidationError("Le montant total accordé ne peut être supérieur au montant conventionné."),
                )
            if (
                advance_amount := self.cleaned_data.get("advance_amount")
            ) is not None and advance_amount > convention_amount:
                self.add_error(
                    "advance_amount",
                    forms.ValidationError(
                        "Le montant du premier versement ne peut être supérieur au montant conventionné."
                    ),
                )
