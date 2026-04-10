from django import forms
from django.forms import widgets
from django.urls import reverse
from django.utils import timezone

from itou.files.forms import ItouFileField
from itou.geiq_assessments.models import Assessment, Employee
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.utils.constants import MB
from itou.utils.templatetags.format_filters import format_int_euros
from itou.utils.types import InclusiveDateRange
from itou.utils.widgets import DuetDatePickerWidget, RemoteAutocompleteSelect2Widget


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

    def __init__(self, *args, geiq_name, antenna_names, existing_main_geiq, existing_antenna_ids, **kwargs):
        super().__init__(*args, **kwargs)
        self.antenna_names = antenna_names
        self.fields["ddets"].form_group_class = "form-group form-group-input-w-lg-66 ms-4 collapse ddets_group"
        self.fields["dreets"].form_group_class = "form-group form-group-input-w-lg-66 ms-4 collapse dreets_group"
        if self["convention_with_ddets"].value():
            # Make sure the collapse state is consistent
            self.fields["convention_with_ddets"].widget.attrs["aria-expanded"] = "true"
            self.fields["ddets"].form_group_class += " show"
        if self["convention_with_dreets"].value():
            # Make sure the collapse state is consistent
            self.fields["convention_with_dreets"].widget.attrs["aria-expanded"] = "true"
            self.fields["dreets"].form_group_class += " show"

        self.fields["main_geiq"].label = geiq_name
        self.fields["main_geiq"].disabled = existing_main_geiq

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
            if field.name.startswith(f"{self.ANTENNA_PREFIX}_"):
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
                "Ce champ est obligatoire.",
            )
        elif cleaned_data.get("convention_with_dreets") and not cleaned_data.get("dreets"):
            self.add_error(
                "dreets",
                "Ce champ est obligatoire.",
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
        help_texts = {
            "geiq_comment": "Ce commentaire est destiné à la DDETS/DREETS. Il vous permet de fournir toutes "
            "les informations que vous jugez utiles pour compléter votre dossier.",
        }

    def __init__(self, *args, instance, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        self.fields["geiq_comment"].required = True


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
    refund_amount = forms.CharField(label="Ordre de reversement", required=False, disabled=True)

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

    def save(self, commit=True):
        self.instance.decision_validated_at = timezone.now()
        return super().save(commit=commit)


def get_field_label_from_instance_funcs(field_name, request):
    fields_display = {
        "employee": lambda employee: employee.get_full_name(),
    }
    qs_infos = {
        "employee": {
            "fields": (
                "employee__first_name",
                "employee__last_name",
            ),
            "lookup": "unaccent__istartswith",
        },
    }
    return fields_display[field_name], qs_infos[field_name]


class ContractFilterForm(forms.Form):
    """
    Allow users to filter the list of contracts.
    """

    FILTER_GROUPS = [
        ["duration_longer_or_equal_90", "duration_strictly_shorter_90"],
        ["start_date_lower", "start_date_upper"],
        ["potential_allowance_1400", "potential_allowance_814", "potential_allowance_0"],
        ["allowance_requested_on", "allowance_requested_off"],
        ["allowance_eligibility_on", "allowance_eligibility_off"],
    ]

    start_date_lower = forms.DateField(label="À partir du", required=False, widget=DuetDatePickerWidget())
    start_date_upper = forms.DateField(
        label="Jusqu'au",
        required=False,
        widget=DuetDatePickerWidget(),
    )
    duration_longer_or_equal_90 = forms.BooleanField(label="Oui", required=False)
    duration_strictly_shorter_90 = forms.BooleanField(label="Non", required=False)
    potential_allowance_1400 = forms.BooleanField(label="1 400 €", required=False)
    potential_allowance_814 = forms.BooleanField(label="814 €", required=False)
    potential_allowance_0 = forms.BooleanField(label="0 €", required=False)
    allowance_requested_on = forms.BooleanField(label="Oui", required=False)
    allowance_requested_off = forms.BooleanField(label="Non", required=False)
    allowance_eligibility_on = forms.BooleanField(label="Oui", required=False)
    allowance_eligibility_off = forms.BooleanField(label="Non", required=False)
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.all(),
        label="Nom du salarié",
        required=False,
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "class": "django-select2",
                "data-ajax--cache": "true",
                "data-ajax--delay": 250,
                "data-ajax--type": "GET",
                "data-minimum-input-length": 1,
                "data-placeholder": "Nom du salarié",
            }
        ),
    )

    def _configure_autocomplete_field(
        self, form_field_name, model_field_name, request, autocomplete_view_name=None, assessment_pk=None
    ):
        self.fields[form_field_name].widget.label_from_instance = get_field_label_from_instance_funcs(
            model_field_name, request
        )[0]
        self.fields[form_field_name].queryset = self.fields[form_field_name].queryset.filter(
            pk__in=self.employee_contracts_qs.values_list(f"{model_field_name}_id", flat=True).distinct()
        )
        kwargs = {"field_name": model_field_name}
        if assessment_pk is not None:
            kwargs["assessment_pk"] = assessment_pk
        self.fields[form_field_name].widget.attrs["data-ajax--url"] = reverse(autocomplete_view_name, kwargs=kwargs)

    def __init__(self, employee_contracts_qs, *args, request, assessment_pk, **kwargs):
        self.employee_contracts_qs = employee_contracts_qs
        super().__init__(*args, **kwargs)

        self._configure_autocomplete_field(
            "employee",
            "employee",
            request,
            autocomplete_view_name="geiq_assessments_views:employee_autocomplete",
            assessment_pk=assessment_pk,
        )

    def clean(self):
        """
        Global validation: check date consistency and normalize times.
        """
        cleaned_data = super().clean()
        start_date_lower = cleaned_data.get("start_date_lower")
        start_date_upper = cleaned_data.get("start_date_upper")
        # Validation of date order
        if start_date_lower and start_date_upper and start_date_lower > start_date_upper:
            self.add_error("start_date_upper", "La date de fin doit être postérieure à la date de début.")
        return cleaned_data

    def filter(self, queryset):
        """
        Apply filters to the given queryset based on cleaned data.
        """
        # If the form is not bound, we don't apply any filter and return the original queryset
        if not self.is_bound:
            return queryset
        # Return none if form is not valid
        if not self.is_valid():
            return queryset.none()

        if any(
            start_at_bounds := (
                self.cleaned_data.get("start_date_lower"),
                self.cleaned_data.get("start_date_upper"),
            )
        ):
            queryset = queryset.filter(start_at__contained_by=InclusiveDateRange(*start_at_bounds))

        # Filter on 90 days (either 90+ or 90-)
        match (
            self.cleaned_data.get("duration_longer_or_equal_90"),
            self.cleaned_data.get("duration_strictly_shorter_90"),
        ):
            case (True, False):
                queryset = queryset.filter(nb_days_in_campaign_year__gte=90)
            case (False, True):
                queryset = queryset.filter(nb_days_in_campaign_year__lt=90)
            case _:
                # (True, True) or (False, False) = no filter
                pass

        # Filter on potential help
        potential_allowance_MAP = {
            "potential_allowance_1400": 1_400,
            "potential_allowance_814": 814,
            "potential_allowance_0": 0,
        }
        checked_amounts = [amount for field, amount in potential_allowance_MAP.items() if self.cleaned_data.get(field)]
        if checked_amounts:
            queryset = queryset.filter(employee__allowance_amount__in=checked_amounts)
        match (
            self.cleaned_data.get("allowance_requested_on"),
            self.cleaned_data.get("allowance_requested_off"),
        ):
            case (True, False):
                queryset = queryset.filter(allowance_requested=True)
            case (False, True):
                queryset = queryset.filter(allowance_requested=False)
        match (
            self.cleaned_data.get("allowance_eligibility_on"),
            self.cleaned_data.get("allowance_eligibility_off"),
        ):
            case (True, False):
                queryset = queryset.filter(allowance_granted=True)
            case (False, True):
                queryset = queryset.filter(allowance_granted=False)
            case _:
                pass

        employee = self.cleaned_data.get("employee")
        if employee:
            queryset = queryset.filter(employee=employee)

        return queryset

    def get_qs_filters_counter(self):
        """
        Get number of filters selected.
        """

        if not hasattr(self, "cleaned_data"):
            return 0

        all_grouped_fields = set(sum(self.FILTER_GROUPS, []))

        count = sum(bool(self.cleaned_data.get(f.name)) for f in self if f.name not in all_grouped_fields)
        count += sum(any(self.cleaned_data.get(f) for f in group) for group in self.FILTER_GROUPS)

        return count
