from django import forms

from itou.eligibility import enums as eligibilty_enums
from itou.eligibility.models import AdministrativeCriteria


class ConfirmEligibilityForm(forms.Form):
    """
    Confirmation is currently required only for SIAEs.
    """

    confirm = forms.BooleanField(
        label=(
            "Le candidat étant éligible à l'IAE, je m'engage à conserver les justificatifs "
            "correspondants aux critères d'éligibilité sélectionnés pour 24 mois, en cas de contrôle."
        )
    )

    def clean_confirm(self):
        if not self.cleaned_data["confirm"]:
            error = "Vous devez confirmer l'éligibilité du candidat."
            raise forms.ValidationError(error)


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

    def __init__(self, user, siae, **kwargs):
        self.user = user
        self.siae = siae
        super().__init__(**kwargs)

        for criterion in AdministrativeCriteria.objects.all():

            if criterion.level == AdministrativeCriteria.Level.LEVEL_1:
                prefix = self.LEVEL_1_PREFIX
            elif criterion.level == AdministrativeCriteria.Level.LEVEL_2:
                prefix = self.LEVEL_2_PREFIX
            else:
                raise RuntimeError(f"Unknown level: {criterion.level}.")

            key = f"{prefix}{criterion.pk}"
            self.fields[key] = forms.BooleanField(required=False, label=criterion.name, help_text=criterion.desc)
            self.fields[key].widget.attrs["class"] = "form-check-input"  # Bootstrap CSS class.
            self.OBJECTS[key] = criterion

    def clean(self):
        selected_objects = [self.OBJECTS[key] for key, selected in self.cleaned_data.items() if selected]

        selected_names = {obj.name for obj in selected_objects}

        if {self.NAME_SENIOR, self.NAME_JUNIOR}.issubset(selected_names):
            raise forms.ValidationError(self.ERROR_SENIOR_JUNIOR)

        if {self.NAME_DETLD_24, self.NAME_DELD_12}.issubset(selected_names):
            raise forms.ValidationError(self.ERROR_LONG_TERM_JOB_SEEKER)

        # No required criterion for authorized prescribers. Stop here.
        if self.user.is_prescriber or not self.siae:
            return selected_objects

        level_1 = [obj for obj in selected_objects if obj.level == AdministrativeCriteria.Level.LEVEL_1]
        level_2 = [obj for obj in selected_objects if obj.level == AdministrativeCriteria.Level.LEVEL_2]

        # For ETTI and AI: 1 criterion level 1 OR 2 level 2 criteria.
        if self.siae.kind == self.siae.KIND_ETTI or self.siae.kind == self.siae.KIND_AI:
            len_valid = len(level_1) or len(level_2) >= 2
            if not len_valid:
                raise forms.ValidationError(self.ERROR_CRITERIA_NUMBER_ETTI_AI)
        # Other: 1 criterion level 1 OR 3 level 2 criteria.
        else:
            len_valid = len(level_1) or len(level_2) >= 3
            if not len_valid:
                raise forms.ValidationError(self.ERROR_CRITERIA_NUMBER)

        return selected_objects
