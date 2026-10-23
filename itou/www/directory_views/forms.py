from django import forms
from django.urls import reverse_lazy

from itou.directory.enums import ContactSubject
from itou.nexus.enums import NexusStructureKind
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class PeopleSearchForm(forms.Form):
    q = forms.ChoiceField(
        label="Rechercher une personne",
        required=False,
        choices=(),
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--cache": "true",
                "data-ajax--delay": 250,
                "data-ajax--type": "GET",
                "data-ajax--url": reverse_lazy("directory:people_autocomplete"),
                "data-allow-clear": "true",
                "data-minimum-input-length": 1,
                "data-placeholder": "Nom ou prénom",
            }
        ),
    )
    types = forms.MultipleChoiceField(
        label="Types de structure",
        choices=NexusStructureKind.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, people=(), **kwargs):
        super().__init__(*args, **kwargs)
        selected_key = self.data.get(self.add_prefix("q")) if self.is_bound else self.initial.get("q")
        selected_person = next((person for person in people if person.recipient_id == selected_key), None)
        self.fields["q"].choices = (
            [(selected_person.recipient_id, selected_person.full_name)] if selected_person else []
        )


class ContactMessageForm(forms.Form):
    subject = forms.ChoiceField(
        label="Objet",
        choices=[("", "Choisir un objet…")] + list(ContactSubject.choices),
    )
    custom_subject = forms.CharField(label="Précisez l'objet", required=False, max_length=255)
    body = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={"placeholder": "Votre message…", "rows": 6}),
        max_length=5000,
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("subject") == ContactSubject.OTHER and not cleaned_data.get("custom_subject"):
            self.add_error("custom_subject", "Précisez l'objet de votre message.")
        elif cleaned_data.get("subject") != ContactSubject.OTHER:
            cleaned_data["custom_subject"] = ""
        return cleaned_data
