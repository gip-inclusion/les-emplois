from django.contrib.admin import widgets
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.apis.exceptions import AddressLookupError


class ItouUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ("kind",)


class UserAdminForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        exclude = ("public_id",)
        widgets = {
            "asp_uid": widgets.AdminTextInputWidget,
        }

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

        nir = self.cleaned_data["nir"]
        if nir and self.instance.nir_already_exists(nir=nir, exclude_pk=self.instance.pk):
            raise ValidationError("Le NIR de ce candidat est déjà associé à un autre utilisateur.")

        if self.instance.is_job_seeker:
            # Update job seeker geolocation
            try:
                self.instance.set_coords(self.cleaned_data["address_line_1"], self.cleaned_data["post_code"])
            except AddressLookupError:
                # Nothing to do: re-raised and already logged as error
                pass
