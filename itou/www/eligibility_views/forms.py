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

    ERROR_CRITERIA_NUMBER = gettext_lazy(
        "Vous devez sélectionner au moins un critère administratif de niveau 1 "
        "ou le cumul d'au moins trois critères de niveau 2."
    )
    ERROR_SENIOR_JUNIOR = gettext_lazy(
        "Vous ne pouvez pas sélectionner en même temps les critères Senior (+50 ans) et Jeunes (-26 ans)."
    )
    ERROR_LONG_TERM_JOB_SEEKER = gettext_lazy(
        "Vous ne pouvez pas sélectionner en même temps les critères DETLD (+ 24 mois) et DELD (12-24 mois)."
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for criterion in AdministrativeCriteria.objects.all():

            if criterion.level == AdministrativeCriteria.Level.LEVEL_1:
                prefix = self.LEVEL_1_PREFIX
            elif criterion.level == AdministrativeCriteria.Level.LEVEL_2:
                prefix = self.LEVEL_2_PREFIX
            else:
                raise RuntimeError(_("Unknown level."))

            key = f"{prefix}{criterion.pk}"
            self.fields[key] = forms.BooleanField(required=False, label=criterion.name, help_text=criterion.desc)
            self.fields[key].widget.attrs["class"] = "form-check-input"  # Bootstrap CSS class.
            self.OBJECTS[key] = criterion

    def clean(self):
        selected_objects = [self.OBJECTS[key] for key, selected in self.cleaned_data.items() if selected]

        selected_names = {obj.name for obj in selected_objects}

        if {"Senior (+50 ans)", "Jeunes (-26 ans)"}.issubset(selected_names):
            raise forms.ValidationError(self.ERROR_SENIOR_JUNIOR)

        if {"DETLD (+ 24 mois)", "DELD (12-24 mois)"}.issubset(selected_names):
            raise forms.ValidationError(self.ERROR_LONG_TERM_JOB_SEEKER)

        if self.user.is_siae_staff:
            level_1 = [obj for obj in selected_objects if obj.level == AdministrativeCriteria.Level.LEVEL_1]
            level_2 = [obj for obj in selected_objects if obj.level == AdministrativeCriteria.Level.LEVEL_2]
            len_valid = len(level_1) or len(level_2) >= 3
            if not len_valid:
                raise forms.ValidationError(self.ERROR_CRITERIA_NUMBER)

        return selected_objects
