from allauth.account.models import EmailAddress
from django import forms
from django.core.exceptions import ValidationError

from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.users.models import User
from itou.utils.address.forms import AddressFormMixin
from itou.utils.resume.forms import ResumeFormMixin
from itou.utils.widgets import DatePickerField, MultipleSwitchCheckboxWidget, SwitchCheckboxWidget


class EditUserInfoForm(AddressFormMixin, ResumeFormMixin, forms.ModelForm):
    """
    Edit a user profile.
    """

    email = forms.EmailField(label="Adresse électronique", widget=forms.TextInput(attrs={"autocomplete": "off"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        has_verified_email = EmailAddress.objects.filter(email=self.instance.email, verified=True)
        if has_verified_email or not self.instance.is_job_seeker:
            # We want the possibility to edit the email of job seekers
            # until they validate their email
            del self.fields["email"]
        if not self.instance.is_job_seeker:
            del self.fields["birthdate"]
            del self.fields["pole_emploi_id"]
            del self.fields["lack_of_pole_emploi_id_reason"]
            del self.fields["resume_link"]
        else:
            self.fields["phone"].required = True
            self.fields["birthdate"].required = True
            self.fields["birthdate"].widget = DatePickerField(
                {
                    "viewMode": "years",
                    "minDate": DatePickerField.min_birthdate().strftime("%Y/%m/%d"),
                    "maxDate": DatePickerField.max_birthdate().strftime("%Y/%m/%d"),
                    "useCurrent": False,
                    "allowInputToggle": False,
                }
            )
            self.fields["birthdate"].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = User
        fields = [
            "email",
            "first_name",
            "last_name",
            "birthdate",
            "phone",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "city_name",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
        ] + ResumeFormMixin.Meta.fields
        help_texts = {
            "birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978",
            "phone": "Par exemple 0610203040",
        }

    def clean(self):
        super().clean()
        if self.instance.is_job_seeker:
            self._meta.model.clean_pole_emploi_fields(self.cleaned_data)


class EditUserEmailForm(forms.Form):

    email = forms.EmailField(
        label="Nouvelle adresse e-mail",
        required=True,
    )
    email_confirmation = forms.EmailField(
        label="Confirmation",
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
    spontaneous = forms.BooleanField(label="Candidatures spontanées", required=False, widget=SwitchCheckboxWidget())

    def __init__(self, *args, **kwargs):
        self.recipient = kwargs.pop("recipient")
        self.siae = kwargs.pop("siae")
        super().__init__(*args, **kwargs)
        self.fields["spontaneous"].initial = NewSpontaneousJobAppEmployersNotification.is_subscribed(self.recipient)

        if self.siae.job_description_through.exists():
            default_pks = self.siae.job_description_through.values_list("pk", flat=True)
            self.subscribed_pks = NewQualifiedJobAppEmployersNotification.recipient_subscribed_pks(
                recipient=self.recipient, default_pks=default_pks
            )
            choices = [
                (job_description.pk, job_description.display_name)
                for job_description in self.siae.job_description_through.all()
            ]
            self.fields["qualified"] = forms.MultipleChoiceField(
                label="Fiches de poste",
                required=False,
                widget=MultipleSwitchCheckboxWidget(),
                choices=choices,
                initial=self.subscribed_pks,
            )

    def save(self):
        if self.cleaned_data.get("spontaneous"):
            NewSpontaneousJobAppEmployersNotification.subscribe(recipient=self.recipient)
        else:
            NewSpontaneousJobAppEmployersNotification.unsubscribe(recipient=self.recipient)

        if self.siae.job_description_through.exists():
            to_subscribe_pks = self.cleaned_data.get("qualified")
            NewQualifiedJobAppEmployersNotification.replace_subscriptions(
                recipient=self.recipient, subscribed_pks=to_subscribe_pks
            )
