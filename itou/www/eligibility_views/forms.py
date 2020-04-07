from django import forms
from django.utils.translation import gettext as _, gettext_lazy

from itou.eligibility.models import AdministrativeCriteria


class ConfirmEligibilityForm(forms.Form):
    """
    Confirmation is currently required only for SIAEs.
    """

    confirm = forms.BooleanField(
        label=gettext_lazy(
            "Je confirme que le candidat remplit les critères d'éligibilité à l'IAE et "
            "m'engage à fournir les justificatifs correspondants en cas de contrôle a posteriori."
        )
    )

    def clean_confirm(self):
        if not self.cleaned_data["confirm"]:
            error = _("Vous devez confirmer l'éligibilité du candidat.")
            raise forms.ValidationError(error)


class AdministrativeCriteriaForm(forms.Form):

    LEVEL_1_PREFIX = "level_1_"
    LEVEL_2_PREFIX = "level_2_"

    OBJECTS = {}

    NAME_SENIOR = "Senior (+50 ans)"
    NAME_JUNIOR = "Jeunes (-26 ans)"
    NAME_DETLD_24 = "DETLD (+ 24 mois)"
    NAME_DELD_12 = "DELD (12-24 mois)"
    NAMES = [NAME_SENIOR, NAME_JUNIOR, NAME_DETLD_24, NAME_DELD_12]

    ERROR_CRITERIA_NUMBER = gettext_lazy(
        "Vous devez sélectionner au moins un critère administratif de niveau 1 "
        "ou le cumul d'au moins trois critères de niveau 2."
    )
    ERROR_CRITERIA_NUMBER_ETTI = gettext_lazy(
        "Erreur dans la sélection des critères administratif, reportez-vous au texte d'aide "
        "\"Règle de validation spéciale pour les ETTI\"."
    )
    ERROR_SENIOR_JUNIOR = gettext_lazy(
        f"Vous ne pouvez pas sélectionner en même temps les critères {NAME_SENIOR} et {NAME_JUNIOR}."
    )
    ERROR_LONG_TERM_JOB_SEEKER = gettext_lazy(
        f"Vous ne pouvez pas sélectionner en même temps les critères {NAME_DETLD_24} et {NAME_DELD_12}."
    )

    def __init__(self, user, siae=None, **kwargs):
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

        # Ensure that `NAME_*` exist in DB.
        existing_names_in_db = [obj.name for obj in self.OBJECTS.values()]
        for name in self.NAMES:
            if name not in existing_names_in_db:
                raise RuntimeError(f"Unknown name: {name}.")

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

        # From 8 April, and until 30 April or beyond: 2 scenarios depending on the type of SIAE.
        # https://docs.google.com/document/d/1PtQHmhe5DaHhG0ud5EHwSMUMBplTvm7WKRNm_AX056Y/edit

        # For EI, AI, ACI:
        # 1 criterion level 1
        #   OR
        # 3 level 2 criteria
        if self.siae.kind != self.siae.KIND_ETTI:
            len_valid = len(level_1) or len(level_2) >= 3
            if not len_valid:
                raise forms.ValidationError(self.ERROR_CRITERIA_NUMBER)

        # For ETTI:
        # 1 criterion level
        #   OR
        # 1 level 2 criterion in ETTI_LEVEL_2_ONE_REQUIRED
        #   OR
        # 3 level 2 criteria in ETTI_LEVEL_2_THREE_REQUIRED:
        if self.siae.kind == self.siae.KIND_ETTI:
            ETTI_LEVEL_2_ONE_REQUIRED = [
                "Sortant de l'ASE",
                "DELD (12-24 mois)",
                "Travailleur handicapé",
                "Personne sans hébergement ou hébergée ou ayant un parcours de rue",
                "Primo arrivant",
                "Résident ZRR",
                "Résident QPV",
            ]
            ETTI_LEVEL_2_THREE_REQUIRED = [
                "Niveau d'étude 3 ou infra",
                "Senior (+50 ans)",
                "Jeunes (-26 ans)",
                "Parent isolé",
            ]
            level_2_one_required = [obj for obj in selected_objects if obj.name in ETTI_LEVEL_2_ONE_REQUIRED]
            level_2_three_required = [obj for obj in selected_objects if obj.name in ETTI_LEVEL_2_THREE_REQUIRED]
            len_valid = len(level_1) or len(level_2_one_required) or len(level_2_three_required) >= 3
            if not len_valid:
                raise forms.ValidationError(self.ERROR_CRITERIA_NUMBER_ETTI)

        return selected_objects
