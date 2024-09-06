import logging
from collections import namedtuple

from django import forms
from django.contrib.admin import widgets
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import ValidationError

from itou.geo.utils import coords_to_geometry
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.apis import geocoding as api_geocoding


logger = logging.getLogger(__name__)


class ItouUserCreationForm(forms.ModelForm):
    def save(self, commit=True):
        self.instance.set_unusable_password()
        return super().save(commit=commit)


class UserAdminForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        exclude = ("public_id", "address_filled_at")

    def clean(self):
        self.cleaned_data["is_staff"] = self.instance.kind == UserKind.ITOU_STAFF

        # smart warning if email already exist
        try:
            email = self.cleaned_data["email"]
        except KeyError:
            # Email already registered, e.g. comes from SSO.
            pass
        else:
            if self.instance.email_already_exists(email, exclude_pk=self.instance.pk):
                raise ValidationError(User.ERROR_EMAIL_ALREADY_EXISTS)

        if self.instance.is_job_seeker:
            # Update job seeker geolocation
            posted_fields = [
                self.cleaned_data["address_line_1"],
                f"{self.cleaned_data['post_code']} {self.cleaned_data['city']}",
            ]
            posted_address = ", ".join([field for field in posted_fields if field])
            if posted_address != self.instance.geocoding_address:
                try:
                    geocoding_data = api_geocoding.get_geocoding_data(posted_address)
                except api_geocoding.GeocodingDataError:
                    logger.error(
                        "No geocoding data could be found for `%s - %s`",
                        self.cleaned_data["address_line_1"],
                        self.cleaned_data["post_code"],
                    )
                else:
                    self.instance.coords = coords_to_geometry(
                        lat=geocoding_data["latitude"], lon=geocoding_data["longitude"]
                    )
                    self.instance.geocoding_score = geocoding_data["score"]


class JobSeekerProfileAdminForm(forms.ModelForm):
    class Meta:
        model = JobSeekerProfile
        fields = "__all__"
        widgets = {
            "asp_uid": widgets.AdminTextInputWidget,
        }


FakeField = namedtuple("FakeField", ("name",))


class FakeRelForToUserRawIdWidget:
    model = User
    limit_choices_to = {
        "kind": UserKind.JOB_SEEKER,
    }

    def get_related_field(self):
        # This must return something that has the name of an existing field
        return FakeField("id")


class ToUserRawIdWidget(widgets.ForeignKeyRawIdWidget):
    def __init__(self, admin_site, attrs=None, using=None):
        super().__init__(FakeRelForToUserRawIdWidget(), admin_site, attrs, using)


class SelectTargetUserForm(forms.Form):
    to_user = forms.ModelChoiceField(
        User.objects.filter(kind=UserKind.JOB_SEEKER), required=True, label="Choisissez l'utilisateur cible"
    )

    def __init__(self, *args, from_user, admin_site, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_user"].widget = ToUserRawIdWidget(admin_site)
        self.from_user = from_user

    def clean_to_user(self):
        to_user = self.cleaned_data["to_user"]
        if to_user.pk == self.from_user.pk:
            raise ValidationError("L'utilisateur cible doit être différent de celui d'origine")
        return to_user


class ChooseFieldsToTransfer(forms.Form):
    fields_to_transfer = forms.MultipleChoiceField(
        choices=[],
        required=True,
        label="Choisissez les objets à transférer",
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, fields_choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fields_to_transfer"].choices = fields_choices
