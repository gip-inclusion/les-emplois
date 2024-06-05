from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify

from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.common_apps.nir.forms import JobSeekerNIRUpdateMixin
from itou.communications import registry as notification_registry
from itou.communications.models import NotificationRecord, NotificationSettings
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
        label="Adresse électronique personnelle",
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

        for required_fieldname in ["title", "birthdate", "first_name", "last_name"]:
            self.fields[required_fieldname].required = True
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


class EditUserInfoForm(SSOReadonlyMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "phone",
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


class EditUserNotificationForm(forms.Form):
    def __init__(self, user, structure, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.structure = structure
        self.layout = {}

        notification_settings = self.user.notification_settings.for_structure(self.structure).first()
        if notification_settings:
            disabled_notifications = [
                disabled.notification_class for disabled in notification_settings.disabled_notifications.all()
            ]
        else:
            disabled_notifications = []

        previous_category = None
        for notification_class in notification_registry:
            notification = notification_class(self.user, self.structure)
            notification_class_name = notification_class.__name__
            category_slug = slugify(notification.category)

            if notification.is_manageable_by_user():
                if previous_category is None or previous_category != notification.category:
                    previous_category = notification.category
                    self.fields[f"category-{category_slug}-all"] = forms.BooleanField(
                        required=False,
                        label="Toutes les notifications",
                        initial=notification_class_name not in disabled_notifications,
                        widget=forms.CheckboxInput(
                            attrs={
                                "class": f"category-{category_slug} category-grouper",
                                "data-category-name": notification.category,
                                "data-category-slug": category_slug,
                            }
                        ),
                    )
                    self.layout[category_slug] = {"name": notification.category, "notifications": []}

                self.fields[notification_class_name] = forms.BooleanField(
                    required=False,
                    label=notification.name,
                    initial=notification_class_name not in disabled_notifications,
                    widget=forms.CheckboxInput(
                        attrs={
                            "class": f"category-{category_slug}",
                            "data-category-slug": category_slug,
                        }
                    ),
                )
                self.layout[category_slug]["notifications"].append(notification_class_name)

    def save(self):
        notification_settings, _ = NotificationSettings.get_or_create(self.user, self.structure)
        disabled_notifications = []

        for field_name, value in self.cleaned_data.items():
            if field_name.startswith("category-"):
                continue
            if not value:
                disabled_notifications.append(NotificationRecord.objects.get(notification_class=field_name))

        notification_settings.disabled_notifications.set(disabled_notifications)
