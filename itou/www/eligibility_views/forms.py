from django import forms

from itou.companies.enums import CompanyKind
from itou.eligibility import enums as eligibilty_enums
from itou.eligibility.models import AdministrativeCriteria
from itou.eligibility.utils import iae_has_required_criteria


class AdministrativeCriteriaForm(forms.Form):
    LEVEL_1_PREFIX = eligibilty_enums.AdministrativeCriteriaLevelPrefix.LEVEL_1_PREFIX
    LEVEL_2_PREFIX = eligibilty_enums.AdministrativeCriteriaLevelPrefix.LEVEL_2_PREFIX

    OBJECTS = {}

    NAME_SENIOR = "Senior (+50 ans)"
    NAME_JUNIOR = "Jeune (-26 ans)"
    NAME_DETLD_24 = "DETLD (+ 24 mois)"
    NAME_DELD_12 = "DELD (12-24 mois)"
    NAMES = [NAME_SENIOR, NAME_JUNIOR, NAME_DETLD_24, NAME_DELD_12]

    ERROR_CRITERIA_NUMBER = (
        "Vous devez sélectionner au moins un critère administratif de niveau 1 "
        "ou le cumul d'au moins trois critères de niveau 2."
    )
    ERROR_CRITERIA_NUMBER_ETTI_AI = (
        "Vous devez sélectionner au moins un critère administratif de niveau 1 "
        "ou le cumul d'au moins deux critères de niveau 2."
    )
    ERROR_SENIOR_JUNIOR = f"Vous ne pouvez pas sélectionner en même temps les critères {NAME_SENIOR} et {NAME_JUNIOR}."
    ERROR_LONG_TERM_JOB_SEEKER = (
        f"Vous ne pouvez pas sélectionner en même temps les critères {NAME_DETLD_24} et {NAME_DELD_12}."
    )

    def get_administrative_criteria(self):
        return AdministrativeCriteria.objects.all()

    def __init__(self, is_authorized_prescriber, siae, **kwargs):
        self.is_authorized_prescriber = is_authorized_prescriber
        self.siae = siae
        super().__init__(**kwargs)

        initial_administrative_criteria = self.initial.get("administrative_criteria", [])
        for criterion in self.get_administrative_criteria():
            key = criterion.key
            self.fields[key] = forms.BooleanField(required=False, label=criterion.name, help_text=criterion.desc)
            self.fields[key].widget.attrs["class"] = "form-check-input"  # Bootstrap CSS class.
            self.initial.setdefault(key, criterion in initial_administrative_criteria)
            self.OBJECTS[key] = criterion

    def clean(self):
        selected_objects = [self.OBJECTS[key] for key, selected in self.cleaned_data.items() if selected]

        selected_names = {obj.name for obj in selected_objects}

        if {self.NAME_SENIOR, self.NAME_JUNIOR}.issubset(selected_names):
            raise forms.ValidationError(self.ERROR_SENIOR_JUNIOR)

        if {self.NAME_DETLD_24, self.NAME_DELD_12}.issubset(selected_names):
            raise forms.ValidationError(self.ERROR_LONG_TERM_JOB_SEEKER)

        # No required criterion for authorized prescribers. Stop here.
        if self.is_authorized_prescriber or not self.siae:
            return selected_objects

        if not iae_has_required_criteria(selected_objects, self.siae.kind):
            message = (
                self.ERROR_CRITERIA_NUMBER_ETTI_AI
                if self.siae.kind in [CompanyKind.AI, CompanyKind.ETTI]
                else self.ERROR_CRITERIA_NUMBER
            )
            raise forms.ValidationError(message)

        return selected_objects
