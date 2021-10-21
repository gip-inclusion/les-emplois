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
        # We may not necessarily have an approvals_wrapper during account creation
        if self.instance.approvals_wrapper:
            has_approval = self.instance.approvals_wrapper.latest_approval is not None
            if has_approval and not self.cleaned_data["is_job_seeker"]:
                raise ValidationError(
                    "Cet utilisateur possède déjà un PASS IAE et doit donc obligatoirement être un candidat."
                )
