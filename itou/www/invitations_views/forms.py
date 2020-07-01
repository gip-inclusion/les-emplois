from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth import get_user_model
from django.forms.models import modelformset_factory
from django.utils.translation import gettext as _, gettext_lazy

from itou.invitations.models import Invitation, SiaeStaffInvitation


class NewInvitationMixinForm(forms.ModelForm):
    """
    ModelForm based on an abstract class. It should not be used alone!
    Inherit from it when you need a new kind of invitation.
    """

    class Meta:
        model = Invitation
        fields = ["first_name", "last_name", "email"]

    def __init__(self, sender, *args, **kwargs):
        self.sender = sender
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"]
        self._invited_user_exists_error(email)
        self._extend_expiration_date_or_error(email)
        return email

    def save(self, commit=True, *args, **kwargs):
        invitation = super().save(commit=False)
        invitation.sender = self.sender
        if commit:
            invitation.save()
            invitation.send()
        return invitation

    def _invited_user_exists_error(self, email):
        user = get_user_model().objects.filter(email__iexact=email).first()
        if user:
            error = forms.ValidationError(_("Cet utilisateur existe déjà."))
            self.add_error("email", error)

    def _extend_expiration_date_or_error(self, email):
        invitation_model = self.Meta.model
        invitation = invitation_model.objects.filter(email__iexact=email).first()
        if invitation:
            if invitation.has_expired:
                invitation.extend_expiration_date()
            else:
                error = forms.ValidationError(_("Cette personne a déjà été invitée."))
                self.add_error("email", error)


class NewSiaeStaffInvitationForm(NewInvitationMixinForm):
    class Meta:
        fields = NewInvitationMixinForm.Meta.fields
        model = SiaeStaffInvitation

    def __init__(self, sender, siae, *args, **kwargs):
        self.siae = siae
        super().__init__(sender=sender, *args, **kwargs)

    def _invited_user_exists_error(self, email):
        """
        An employer can only invite another employer to join his structure.
        """
        self.user = get_user_model().objects.filter(email__iexact=email).first()
        if self.user:
            if not self.user.is_siae_staff:
                error = forms.ValidationError(_("Cet utilisateur n'est pas un employeur."))
                self.add_error("email", error)
            user_is_member = self.siae.members.filter(email=self.user.email).exists()
            if user_is_member:
                error = forms.ValidationError(_("Cette personne fait déjà partie de votre structure."))
                self.add_error("email", error)

    def _extend_expiration_date_or_error(self, email):
        invitation_model = self.Meta.model
        invitation = invitation_model.objects.filter(email__iexact=email, siae=self.siae).first()
        if invitation:
            if invitation.accepted:
                error = forms.ValidationError(_("Cette personne a déjà accepté votre précédente invitation."))
                self.add_error("email", error)
            else:
                invitation.extend_expiration_date()

    def save(self, *args, **kwargs):
        invitation = super().save(commit=False)
        invitation.siae = self.siae
        invitation.save()
        invitation.send()
        return invitation


class SiaeStaffInvitationFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        """
        By default, BaseModelFormSet show the objects stored in the DB.
        See https://docs.djangoproject.com/en/3.0/topics/forms/modelforms/#changing-the-queryset
        """
        super().__init__(*args, **kwargs)
        self.queryset = SiaeStaffInvitation.objects.none()


"""
Formset used when an employer invites other employers to join his structure.
"""
NewSiaeStaffInvitationFormSet = modelformset_factory(
    SiaeStaffInvitation, form=NewSiaeStaffInvitationForm, formset=SiaeStaffInvitationFormSet, extra=1, max_num=30
)


class NewUserForm(SignupForm):
    """
    Signup form shown when a user accepts an invitation.
    """

    first_name = forms.CharField(
        label=gettext_lazy("Prénom"),
        max_length=get_user_model()._meta.get_field("first_name").max_length,
        required=True,
        strip=True,
    )

    last_name = forms.CharField(
        label=gettext_lazy("Nom"),
        max_length=get_user_model()._meta.get_field("last_name").max_length,
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

    def save(self, request):
        self.cleaned_data["email"] = self.email
        DefaultAccountAdapter().stash_verified_email(request, self.email)
        # Possible problem: this causes the user to be saved twice.
        # If we want to save it once, we should override the Allauth method.
        # See https://github.com/pennersr/django-allauth/blob/master/allauth/account/forms.py#L401
        user = super().save(request)
        user = self.invitation.set_guest_type(user)
        user.save()
        return user
