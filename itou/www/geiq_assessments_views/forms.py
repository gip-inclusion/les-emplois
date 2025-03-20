from django import forms

from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution


class CreateForm(forms.Form):
    main_geiq = forms.BooleanField()

    convention_with_ddets = forms.BooleanField()
    ddets = forms.ModelChoiceField(
        queryset=Institution.objects.filter(kind=InstitutionKind.DDETS_GEIQ), required=False
    )
    convention_with_dreets = forms.BooleanField()
    dreets = forms.ModelChoiceField(
        queryset=Institution.objects.filter(kind=InstitutionKind.DREETS_GEIQ), required=False
    )

    def __init__(self, geiq_name, antennas):
        self.fields["main_geiq"].label = geiq_name

        for antenna in antennas:
            if antenna_id := antenna["id"]:  # Ignore main geiq with id 0
                self.fields[f"antenna_{antenna_id}"] = forms.BooleanField(label=antenna["name"])
