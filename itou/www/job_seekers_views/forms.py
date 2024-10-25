from django import forms
from django.utils.html import format_html
from django_select2.forms import Select2Widget

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.emails import redact_email_address
from itou.utils.validators import validate_nir


class FilterForm(forms.Form):
    job_seeker = forms.ChoiceField(
        required=False,
        label="Nom",
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom du candidat",
            }
        ),
    )

    def __init__(self, job_seeker_qs, data, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.fields["job_seeker"].choices = [
            (job_seeker.pk, job_seeker.get_full_name())
            for job_seeker in job_seeker_qs.order_by("first_name", "last_name")
            if job_seeker.get_full_name()
        ]


class CheckJobSeekerNirForm(forms.Form):
    nir = forms.CharField(
        label="Numéro de sécurité sociale",
        max_length=21,  # 15 + 6 white spaces
        required=True,
        strip=True,
        validators=[validate_nir],
        widget=forms.TextInput(
            attrs={
                "placeholder": "2 69 05 49 588 157 80",
            }
        ),
    )

    def __init__(self, *args, job_seeker=None, is_gps=False, **kwargs):
        self.job_seeker = job_seeker
        super().__init__(*args, **kwargs)
        if self.job_seeker:
            self.fields["nir"].label = "Votre numéro de sécurité sociale"
        else:
            self.fields["nir"].label = "Numéro de sécurité sociale du " + ("bénéficiaire" if is_gps else "candidat")

    def clean_nir(self):
        nir = self.cleaned_data["nir"].upper()
        nir = nir.replace(" ", "")
        existing_account = User.objects.filter(jobseeker_profile__nir=nir).first()

        # Job application sent by autonomous job seeker.
        if self.job_seeker:
            if existing_account:
                error_message = (
                    "Ce numéro de sécurité sociale est déjà utilisé par un autre compte. Merci de vous "
                    "reconnecter avec l'adresse e-mail <b>{}</b>. "
                    "Si vous ne vous souvenez plus de votre mot de passe, vous pourrez "
                    "cliquer sur « mot de passe oublié ». "
                    'En cas de souci, vous pouvez <a href="{}" rel="noopener" '
                    'target="_blank" aria-label="Ouverture dans un nouvel onglet">nous contacter</a>.'
                )
                raise forms.ValidationError(
                    format_html(
                        error_message,
                        redact_email_address(existing_account.email),
                        global_constants.ITOU_HELP_CENTER_URL,
                    )
                )
        else:
            # For the moment, consider NIR to be unique among users.
            self.job_seeker = existing_account
        return nir

    def clean(self):
        super().clean()
        if self.job_seeker and self.job_seeker.kind != UserKind.JOB_SEEKER:
            error_message = (
                "Vous ne pouvez postuler pour cet utilisateur car ce numéro de sécurité sociale "
                "n'est pas associé à un compte candidat."
            )
            raise forms.ValidationError(error_message)

    def get_job_seeker(self):
        return self.job_seeker
