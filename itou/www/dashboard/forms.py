from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse

from itou.common_apps.address.forms import OptionalAddressFormMixin
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.users.models import User
from itou.utils.perms.user import is_user_france_connected
from itou.utils.widgets import DuetDatePickerWidget, MultipleSwitchCheckboxWidget, SwitchCheckboxWidget


class EditUserInfoForm(OptionalAddressFormMixin, forms.ModelForm):
    """
    Edit a user profile.
    """

    email = forms.EmailField(label="Adresse électronique", widget=forms.TextInput(attrs={"autocomplete": "off"}))

    def __init__(self, *args, **kwargs):
        editor = kwargs.pop("editor")
        request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        user_france_connected = is_user_france_connected(request)

        if not self.instance.is_job_seeker:
            del self.fields["birthdate"]
            del self.fields["pole_emploi_id"]
            del self.fields["lack_of_pole_emploi_id_reason"]
        else:
            self.fields["phone"].required = True
            self.fields["birthdate"].required = True
            self.fields["birthdate"].widget = DuetDatePickerWidget(
                attrs={
                    "min": DuetDatePickerWidget.min_birthdate(),
                    "max": DuetDatePickerWidget.max_birthdate(),
                }
            )

        if user_france_connected:
            # When a user is logged-in through France Connect,
            # it should see the field but most should be disabled
            # (that’s a requirement on FC’s side)
            disabled_fields = ["first_name", "last_name", "email", "birthdate"]
            for field_name in disabled_fields:
                self.fields[field_name].disabled = True

            edit_email_url = reverse("dashboard:edit_user_email")
            self.fields["email"].help_text = f'<a href="{edit_email_url}"> Modifier votre adresse email</a>'
        else:
            # Noboby can edit its own email.
            # Only prescribers and employers can edit the job seeker's email here under certain conditions
            if not self.instance.is_job_seeker or not editor.can_edit_email(self.instance):
                del self.fields["email"]

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
            "city_slug",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
        ]
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
