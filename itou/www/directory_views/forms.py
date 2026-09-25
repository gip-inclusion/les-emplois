from django import forms

from itou.directory.enums import ContactSubject
from itou.nexus.enums import NexusStructureKind


class PeopleSearchForm(forms.Form):
    q = forms.CharField(
        label="Rechercher une personne",
        required=False,
        widget=forms.TextInput(
            attrs={
                "id": "q-personnes",
                "placeholder": "Nom ou prénom",
                "autocomplete": "off",
                "class": "form-control",
            }
        ),
    )
    types = forms.MultipleChoiceField(
        label="Types de structure",
        choices=NexusStructureKind.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )


class ContactMessageForm(forms.Form):
    subject = forms.ChoiceField(
        label="Objet",
        choices=[("", "Sélectionnez un objet")] + list(ContactSubject.choices),
    )
    custom_subject = forms.CharField(label="Précisez l'objet", required=False, max_length=255)
    body = forms.CharField(label="Votre message", widget=forms.Textarea, max_length=5000)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("subject") == ContactSubject.OTHER and not cleaned_data.get("custom_subject"):
            self.add_error("custom_subject", "Précisez l'objet de votre message.")
        elif cleaned_data.get("subject") != ContactSubject.OTHER:
            cleaned_data["custom_subject"] = ""
        return cleaned_data
