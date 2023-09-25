from collections import namedtuple

from django import forms
from django.contrib.admin import widgets
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import ValidationError

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.apis.exceptions import AddressLookupError


class ItouUserCreationForm(forms.ModelForm):
    def save(self, commit=True):
        self.instance.set_unusable_password()
        return super().save(commit=commit)


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
    # Needed to avoid RemovedInDjango50Warning
    template_name = forms.Form.template_name_div

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
    # Needed to avoid RemovedInDjango50Warning
    template_name = forms.Form.template_name_div

    fields_to_transfer = forms.MultipleChoiceField(
        choices=[],
        required=True,
        label="Choisissez les objets à transférer",
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, fields_choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fields_to_transfer"].choices = fields_choices
