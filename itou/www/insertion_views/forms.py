from django import forms
from django.forms import ValidationError
from django_select2.forms import Select2Widget

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.templatetags.str_filters import mask_unless


class OrientationSelectJobSeekerForm(forms.Form):
    job_seeker = forms.ChoiceField(
        required=True,
        label="Nom de l'usager",
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom de l'usager",
            }
        ),
    )

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        job_seekers_ids = User.objects.assigned_job_seeker_ids(request.user, request.current_organization)
        job_seeker_qs = User.objects.filter(kind=UserKind.JOB_SEEKER, pk__in=job_seekers_ids).order_by(
            "last_name", "first_name"
        )
        self.valid_public_ids = set()
        choices = [("", "---------")]
        for job_seeker in job_seeker_qs:
            if not job_seeker.get_inverted_full_name():
                continue
            self.valid_public_ids.add(str(job_seeker.public_id))
            choices.append(
                (
                    str(job_seeker.public_id),
                    mask_unless(
                        job_seeker.get_inverted_full_name(),
                        predicate=can_view_personal_information(request, job_seeker),
                    ),
                )
            )
        self.fields["job_seeker"].choices = choices

    def clean_job_seeker(self):
        public_id = self.cleaned_data["job_seeker"]
        if public_id not in self.valid_public_ids:
            raise ValidationError("Sélectionnez un usager valide.")
        return public_id


class OrientationConformityForm(forms.Form):
    confirms_conditions = forms.BooleanField(
        required=True,
        label="Je confirme que le candidat répond aux critères d'éligibilité du service",
    )


class OrientationReferentForm(forms.Form):
    referent_last_name = forms.CharField(required=True, label="Nom")
    referent_first_name = forms.CharField(required=True, label="Prénom")
    referent_phone = forms.CharField(
        required=True,
        label="Téléphone",
        help_text="Ex : 0123456789",
        widget=forms.TextInput(attrs={"type": "tel"}),
    )
    referent_email = forms.EmailField(required=True, label="Adresse e-mail", help_text="Ex : mail@domaine.fr")
    orientation_reason = forms.CharField(
        required=False,
        label="Motif de l'orientation",
        widget=forms.Textarea(attrs={"placeholder": "Placeholder", "rows": 4}),
    )
