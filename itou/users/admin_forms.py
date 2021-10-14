from django import forms
from django.core.exceptions import ValidationError

from itou.users.models import User


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = "__all__"

    def clean(self):
        roles_count = (
            int(self.cleaned_data["is_job_seeker"])
            + int(self.cleaned_data["is_prescriber"])
            + int(self.cleaned_data["is_siae_staff"])
            + int(self.cleaned_data["is_labor_inspector"])
        )
        if roles_count != 1:
            raise ValidationError(
                "Un utilisateur ne peut avoir qu'un rôle à la fois : soit candidat, soit prescripteur, "
                "soit employeur, soit inspecteur."
            )
