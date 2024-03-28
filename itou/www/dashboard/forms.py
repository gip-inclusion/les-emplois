from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.common_apps.address.forms import JobSeekerAddressForm, OptionalAddressFormMixin
from itou.common_apps.nir.forms import JobSeekerNIRUpdateMixin
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.users.enums import IdentityProvider
from itou.users.forms import JobSeekerProfileFieldsMixin
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.widgets import DuetDatePickerWidget


class SSOReadonlyMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.has_sso_provider and self.instance.identity_provider != IdentityProvider.PE_CONNECT:
            # When a user has logged in with a SSO other than PEAMU
            # it should see the field but most should be disabled
            # (that’s a requirement on FranceConnect’s side).
            disabled_fields = ["first_name", "last_name", "email", "birthdate"]
            for name in self.fields.keys():
                if name in disabled_fields:
                    self.fields[name].disabled = True


class EditJobSeekerInfoForm(
    JobSeekerNIRUpdateMixin, JobSeekerProfileFieldsMixin, JobSeekerAddressForm, SSOReadonlyMixin, forms.ModelForm
):
    """
    Edit a job seeker profile.
    """

    PROFILE_FIELDS = ["pole_emploi_id", "lack_of_pole_emploi_id_reason", "nir", "lack_of_nir_reason"]

    email = forms.EmailField(
        label="Adresse électronique",
        disabled=True,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    class Meta:
        model = User
        fields = [
            "email",
            "title",
            "first_name",
            "last_name",
            "birthdate",
            "phone",
        ] + JobSeekerAddressForm.Meta.fields

        help_texts = {
            "birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978",
            "phone": "L'ajout du numéro de téléphone permet à l'employeur de vous contacter plus facilement.",
        }

    def __init__(self, *args, **kwargs):
        editor = kwargs.get("editor", None)
        super().__init__(*args, **kwargs)
        assert self.instance.is_job_seeker, self.instance

        self.fields["title"].required = True
        self.fields["birthdate"].required = True
        self.fields["birthdate"].widget = DuetDatePickerWidget(
            attrs={
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )

        # Noboby can edit its own email.
        if self.instance.identity_provider == IdentityProvider.FRANCE_CONNECT:
            # If the job seeker uses France Connect, point them to the modification process
            self.fields["email"].help_text = (
                "Si vous souhaitez modifier votre adresse e-mail merci de "
                f"<a href='{global_constants.ITOU_HELP_CENTER_URL}/requests/new' target='_blank'>"
                "contacter notre support technique</a>"
            )
        elif editor and editor.can_edit_email(self.instance):
            # Only prescribers and employers can edit the job seeker's email here under certain conditions
            self.fields["email"].disabled = False
        else:
            # Otherwise, hide the field
            self.fields["email"].widget = forms.HiddenInput()

    def clean(self):
        super().clean()
        JobSeekerProfile.clean_pole_emploi_fields(self.cleaned_data)

    def save(self, commit=True):
        self.instance.last_checked_at = timezone.now()

        if self.instance.ban_api_resolved_address == "":
            self.instance.ban_api_resolved_address = None

        return super().save(commit=commit)


class EditUserInfoForm(OptionalAddressFormMixin, SSOReadonlyMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "phone",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "city_slug",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        assert not self.instance.is_job_seeker, self.instance

    def save(self, commit=True):
        self.instance.last_checked_at = timezone.now()
        return super().save(commit=commit)


class EditUserEmailForm(forms.Form):
    email = forms.EmailField(
        label="Nouvelle adresse e-mail",
        widget=forms.EmailInput(attrs={"placeholder": "prenom.nom@example.com"}),
        required=True,
    )
    email_confirmation = forms.EmailField(
        label="Confirmation de l'adresse e-mail",
        widget=forms.EmailInput(attrs={"placeholder": "prenom.nom@example.com"}),
        required=True,
    )

    def __init__(self, *args, **kwargs):
        self.user_email = kwargs.pop("user_email")
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        email = self.cleaned_data.get("email")
        email_confirmation = self.cleaned_data.get("email_confirmation")
        if email != email_confirmation:
            raise ValidationError("Les deux adresses sont différentes.")
        return self.cleaned_data

    def clean_email(self):
        email = self.cleaned_data["email"]
        if email == self.user_email:
            raise ValidationError("Veuillez indiquer une adresse différente de l'actuelle.")
        if User.objects.filter(email=email):
            raise ValidationError("Cette adresse est déjà utilisée par un autre utilisateur.")
        return email


class EditNewJobAppEmployersNotificationForm(forms.Form):
    spontaneous = forms.BooleanField(label="Candidatures spontanées", required=False)

    def __init__(self, recipient, company, *args, **kwargs):
        self.recipient = recipient
        self.company = company
        super().__init__(*args, **kwargs)
        self.fields["spontaneous"].initial = NewSpontaneousJobAppEmployersNotification.is_subscribed(self.recipient)

        if self.company.job_description_through.exists():
            default_pks = self.company.job_description_through.values_list("pk", flat=True)
            self.subscribed_pks = NewQualifiedJobAppEmployersNotification.recipient_subscribed_pks(
                recipient=self.recipient, default_pks=default_pks
            )
            choices = [
                (job_description.pk, job_description.display_name)
                for job_description in self.company.job_description_through.all()
            ]
            self.fields["qualified"] = forms.MultipleChoiceField(
                label="Fiches de poste",
                required=False,
                widget=forms.CheckboxSelectMultiple(),
                choices=choices,
                initial=self.subscribed_pks,
            )

    def save(self):
        if self.cleaned_data.get("spontaneous"):
            NewSpontaneousJobAppEmployersNotification.subscribe(recipient=self.recipient)
        else:
            NewSpontaneousJobAppEmployersNotification.unsubscribe(recipient=self.recipient)

        if self.company.job_description_through.exists():
            to_subscribe_pks = self.cleaned_data.get("qualified")
            NewQualifiedJobAppEmployersNotification.replace_subscriptions(
                recipient=self.recipient, subscribed_pks=to_subscribe_pks
            )
