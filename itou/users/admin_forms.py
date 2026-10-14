import logging
import uuid

from django import forms
from django.contrib.admin import widgets
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import ValidationError

from itou.geo.utils import coords_to_geometry
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.admin import FakeRelForRawIdWidget
from itou.utils.apis import geocoding as api_geocoding


logger = logging.getLogger(__name__)


class ItouUserCreationForm(forms.ModelForm):
    def save(self, commit=True):
        if not self.instance.username:  # This field is not in ItouUserAdmin.add_fieldsets
            self.instance.username = str(uuid.uuid4())
        # Use ProConnect for pro and staff users
        # We could check settings.FORCE_PROCONNECT_LOGIN_* but this view
        # is only really used on prod where both are true so it's simpler this way
        if self.instance.kind in [UserKind.PROFESSIONAL, UserKind.ITOU_STAFF]:
            self.instance.identity_provider = IdentityProvider.PRO_CONNECT
        if self.instance.is_itou_staff:
            # A the first login, ProConnect will give us the real sub that won't match
            # the random uuid we just used as sub.
            self.instance.allow_next_sso_sub_update = True
        self.instance.set_unusable_password()
        return super().save(commit=commit)


class UserAdminForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        exclude = (
            "public_id",
            "address_filled_at",
            "fields_history",
        )

    def clean(self):
        super().clean()
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
                    logger.info(
                        "No geocoding data could be found for the address of <%s - pk=%s>",
                        self.instance.__class__,
                        self.instance.pk,
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

    def clean_asp_uid(self):
        asp_uid = self.cleaned_data.get("asp_uid")
        if not asp_uid:
            return self.instance._default_asp_uid()
        return asp_uid.lower()


class SelectTargetUserForm(forms.Form):
    to_user = forms.ModelChoiceField(
        User.objects.filter(kind=UserKind.JOB_SEEKER), required=True, label="Choisissez l'utilisateur cible"
    )

    def __init__(self, *args, from_user, admin_site, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_user"].widget = widgets.ForeignKeyRawIdWidget(
            FakeRelForRawIdWidget(User, {"kind": UserKind.JOB_SEEKER}), admin_site
        )
        self.from_user = from_user

    def clean_to_user(self):
        to_user = self.cleaned_data["to_user"]
        if to_user.pk == self.from_user.pk:
            raise ValidationError("L'utilisateur cible doit être différent de celui d'origine")
        return to_user
