import uuid

from django import forms
from django_select2.forms import Select2Widget

from itou.nexus.enums import NexusStructureKind


class PeopleSearchForm(forms.Form):
    q = forms.TypedChoiceField(
        coerce=uuid.UUID,
        label="Rechercher une personne",
        required=False,
        choices=(),
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom ou prénom",
            }
        ),
    )
    kind = forms.MultipleChoiceField(
        label="Type de structure",
        choices=NexusStructureKind.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, people, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].choices = ((str(person.public_id), person.get_inverted_full_name()) for person in people)
