from allauth.account.adapter import get_adapter
from allauth.account.forms import SignupForm
from django import forms
from django.conf import settings
from django.forms.models import modelformset_factory
from django.utils.translation import gettext as _, gettext_lazy

from itou.invitations.models import PrescriberWithOrgInvitation, SiaeStaffInvitation
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User


########################################################################
##################### PrescriberWithOrg invitation #####################
########################################################################


class NewPrescriberWithOrgInvitationForm(forms.ModelForm):
    class Meta:
        model = PrescriberWithOrgInvitation
        fields = ["first_name", "last_name", "email"]

    def __init__(self, sender, organization, *args, **kwargs):
        self.sender = sender
        self.organization = organization
        super().__init__(*args, **kwargs)

    def _invited_user_exists_error(self, email):
        """
        If the guest is already a user, he should be a prescriber whether he
        belongs to another organization or not
        """
        user = User.objects.filter(email__iexact=email).first()
        if user:
            if not user.is_prescriber:
                error = forms.ValidationError(_("Cet utilisateur n'est pas un prescripteur."))
                self.add_error("email", error)
            else:
                user_is_member = self.organization.active_members.filter(email=user.email).exists()
                if user_is_member:
                    error = forms.ValidationError(_("Cette personne fait déjà partie de votre organisation."))
                    self.add_error("email", error)

    def _extend_expiration_date_or_error(self, email):
        invitation_model = self.Meta.model
        invitation = invitation_model.objects.filter(email__iexact=email, organization=self.organization).first()
        if invitation:
            # We can re-invite *deactivated* members,
            # even if they already received an invitation
            user_is_member = self.organization.active_members.filter(email=email).exists()
            if invitation.accepted and user_is_member:
                error = forms.ValidationError(_("Cette personne a déjà accepté votre précédente invitation."))
                self.add_error("email", error)
            else:
                # FIXME Wrong instance
                invitation.extend_expiration_date()

    def clean_email(self):
        email = self.cleaned_data["email"]

        self._invited_user_exists_error(email)
        self._extend_expiration_date_or_error(email)
        if self.organization.kind == PrescriberOrganization.Kind.PE and not email.endswith(
            settings.POLE_EMPLOI_EMAIL_SUFFIX
        ):
            error = forms.ValidationError(_("L'adresse e-mail doit être une adresse Pôle emploi"))
            self.add_error("email", error)
        return email

    def save(self, *args, **kwargs):  # pylint: disable=unused-argument
        invitation = super().save(commit=False)
        invitation.sender = self.sender
        invitation.organization = self.organization
        invitation.save()
        return invitation


class PrescriberWithOrgInvitationFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        """
        By default, BaseModelFormSet show the objects stored in the DB.
        See https://docs.djangoproject.com/en/3.0/topics/forms/modelforms/#changing-the-queryset
        """
        super().__init__(*args, **kwargs)
        self.queryset = PrescriberWithOrgInvitation.objects.none()
        # Any access to `self.forms` must be performed after any access to `self.queryset`,
        # otherwise `self.queryset` will have no effect.
        # https://code.djangoproject.com/ticket/31879
        self.forms[0].empty_permitted = False


#
# Formset used when a prescriber invites a person to join his structure.
#
NewPrescriberWithOrgInvitationFormSet = modelformset_factory(
    PrescriberWithOrgInvitation,
    form=NewPrescriberWithOrgInvitationForm,
    formset=PrescriberWithOrgInvitationFormSet,
    extra=1,
    max_num=30,
)


#############################################################
###################### SiaeStaffInvitation ##################
#############################################################


class NewSiaeStaffInvitationForm(forms.ModelForm):
    class Meta:
        fields = ["first_name", "last_name", "email"]
        model = SiaeStaffInvitation

    def __init__(self, sender, siae, *args, **kwargs):
        self.sender = sender
        self.siae = siae
        super().__init__(*args, **kwargs)

    def _invited_user_exists_error(self, email):
        """
        An employer can only invite another employer to join his structure.
        """
        user = User.objects.filter(email__iexact=email).first()
        if user:
            if not user.is_siae_staff:
                error = forms.ValidationError(_("Cet utilisateur n'est pas un employeur."))
                self.add_error("email", error)
            else:
                user_is_member = self.siae.active_members.filter(email=user.email).exists()
                if user_is_member:
                    error = forms.ValidationError(_("Cette personne fait déjà partie de votre structure."))
                    self.add_error("email", error)

    def _extend_expiration_date_or_error(self, email):
        invitation_model = self.Meta.model
        invitation = invitation_model.objects.filter(email__iexact=email, siae=self.siae).first()
        # We can re-invite *deactivated* members,
        # even if they already received an invitation
        user_is_member = self.siae.active_members.filter(email=email).exists()

        if invitation:
            if invitation.accepted and user_is_member:
                error = forms.ValidationError(_("Cette personne a déjà accepté votre précédente invitation."))
                self.add_error("email", error)
            else:
                # WARNING The form is now bound to this instance
                self.instance = invitation
                self.instance.extend_expiration_date()

    def clean_email(self):
        email = self.cleaned_data["email"]
        self._invited_user_exists_error(email)
        self._extend_expiration_date_or_error(email)
        return email

    def save(self, *args, **kwargs):  # pylint: disable=unused-argument
        invitation = super().save(commit=False)
        invitation.sender = self.sender
        invitation.siae = self.siae
        invitation.save()
        return invitation


class SiaeStaffInvitationFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        """
        By default, BaseModelFormSet show the objects stored in the DB.
        See https://docs.djangoproject.com/en/3.0/topics/forms/modelforms/#changing-the-queryset
        """
        super().__init__(*args, **kwargs)
        self.queryset = SiaeStaffInvitation.objects.none()
        # Any access to `self.forms` must be performed after any access to `self.queryset`,
        # otherwise `self.queryset` will have no effect.
        # https://code.djangoproject.com/ticket/31879
        self.forms[0].empty_permitted = False


#
# Formset used when an employer invites other employers to join his structure.
#
NewSiaeStaffInvitationFormSet = modelformset_factory(
    SiaeStaffInvitation, form=NewSiaeStaffInvitationForm, formset=SiaeStaffInvitationFormSet, extra=1, max_num=30
)


###############################################################
######################### Signup forms ########################
###############################################################


class NewUserForm(SignupForm):
    """
    Signup form shown when a user accepts an invitation.
    """

    first_name = forms.CharField(
        label=gettext_lazy("Prénom"),
        max_length=User._meta.get_field("first_name").max_length,
        required=True,
        strip=True,
    )

    last_name = forms.CharField(
        label=gettext_lazy("Nom"),
        max_length=User._meta.get_field("last_name").max_length,
        required=True,
        strip=True,
    )

    class Meta:
        fields = ["first_name", "last_name", "password1", "password2"]

    def __init__(self, invitation, *args, **kwargs):
        # Do not let a guest change his email when signing up.
        self.email = invitation.email
        self.invitation = invitation
        super().__init__(*args, **kwargs)
        self.fields.pop("email")
        self.fields["first_name"].initial = invitation.first_name
        self.fields["last_name"].initial = invitation.last_name

    def clean(self):
        if isinstance(self.invitation, SiaeStaffInvitation) and not self.invitation.siae.is_active:
            raise forms.ValidationError(_("Cette structure n'est plus active."))
        super().clean()

    def save(self, request):
        self.cleaned_data["email"] = self.email
        get_adapter().stash_verified_email(request, self.email)
        # Possible problem: this causes the user to be saved twice.
        # If we want to save it once, we should override the Allauth method.
        # See https://github.com/pennersr/django-allauth/blob/master/allauth/account/forms.py#L401
        user = super().save(request)
        user = self.invitation.set_guest_type(user)
        user.save()
        return user
