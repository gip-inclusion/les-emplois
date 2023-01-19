from django.contrib.admin import widgets
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import ValidationError

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.apis.exceptions import AddressLookupError


class UserAdminForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        widgets = {
            "asp_uid": widgets.AdminTextInputWidget,
        }

    def clean(self):
        roles_count = (
            int(self.cleaned_data["is_job_seeker"])
            + int(self.cleaned_data["is_prescriber"])
            + int(self.cleaned_data["is_siae_staff"])
            + int(self.cleaned_data["is_labor_inspector"])
        )
        if roles_count != 1:
            raise ValidationError(
                "Un utilisateur ne peut avoir qu'un rôle à la fois : soit candidat, soit prescripteur, "
                "soit employeur, soit inspecteur."
            )
        if "kind" not in self.cleaned_data:
            raise ValidationError("Le type est obligatoire")

        self.cleaned_data["is_staff"] = self.cleaned_data["kind"] == UserKind.ITOU_STAFF

        # According to the PR which introduced it, we only care about PASS IAE here,
        # not common approvals. https://github.com/betagouv/itou/pull/910
        # The goal being to prevent changing the type of an user who already has a PASS IAE,
        # and the PE approvals being not linked to an user, we have no need to check those.
        if self.instance.latest_approval and self.cleaned_data["kind"] != UserKind.JOB_SEEKER:
            raise ValidationError(
                "Cet utilisateur possède déjà un PASS IAE et doit donc obligatoirement être un candidat."
            )

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
