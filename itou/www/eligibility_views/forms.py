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


ADMINISTRATIVE_CRITERIA_ERROR_FOR_SIAE = gettext_lazy(
    "Vous devez sélectionner au moins un critère administratif de niveau 1 "
    "ou le cumul d'au moins trois critères de niveau 2."
)


class AdministrativeCriteriaLevel1Form(forms.Form):

    FIELD_PREFIX = "level_1_"
    OBJECTS = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for criterion in AdministrativeCriteria.objects.level1():
            key = f"{self.FIELD_PREFIX}{criterion.pk}"
            self.fields[key] = forms.BooleanField(required=False, label=criterion.name, help_text=criterion.desc)
            self.OBJECTS[key] = criterion

    def clean(self):
        return [self.OBJECTS[key] for key, selected in self.cleaned_data.items() if selected]


class AdministrativeCriteriaLevel2Form(forms.Form):

    FIELD_PREFIX = "level_2_"
    OBJECTS = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for criterion in AdministrativeCriteria.objects.level2():
            key = f"{self.FIELD_PREFIX}{criterion.pk}"
            self.fields[key] = forms.BooleanField(required=False, label=criterion.name, help_text=criterion.desc)
            self.OBJECTS[key] = criterion

    def clean(self):
        return [self.OBJECTS[key] for key, selected in self.cleaned_data.items() if selected]
