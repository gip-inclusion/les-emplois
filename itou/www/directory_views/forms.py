from django import forms
from django_select2.forms import Select2Widget

from itou.directory.enums import ContactSubject
from itou.directory.models import ContactMessage
from itou.nexus.enums import NexusStructureKind


class PeopleSearchForm(forms.Form):
    q = forms.ChoiceField(
        label="Rechercher une personne",
        required=False,
        choices=(),
        widget=Select2Widget(
            attrs={
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

    def __init__(self, *args, people, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].choices = ((person.recipient_id, person.full_name) for person in people)


class ContactMessageForm(forms.ModelForm):
    body = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={"placeholder": "Votre message…", "rows": 6}),
    )

    class Meta:
        model = ContactMessage
        fields = ["subject", "custom_subject"]
        labels = {
            "custom_subject": "Précisez l’objet",
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("subject") == ContactSubject.OTHER and not cleaned_data.get("custom_subject"):
            self.add_error("custom_subject", "Précisez l'objet de votre message.")
        elif cleaned_data.get("subject") != ContactSubject.OTHER:
            cleaned_data["custom_subject"] = ""
        return cleaned_data
