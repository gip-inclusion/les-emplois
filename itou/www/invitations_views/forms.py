from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth import get_user_model
from django.forms.models import modelformset_factory
from django.utils.translation import gettext as _, gettext_lazy

from itou.invitations.models import Invitation


class NewInvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["first_name", "last_name", "email"]

    def __init__(self, sender, *args, **kwargs):
        self.sender = sender
        super(NewInvitationForm, self).__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"]
        self._invited_user_exists_error(email)
        self._extend_expiration_date_or_error(email)
        return email

    def save(self, *args, **kwargs):
        invitation = super(NewInvitationForm, self).save(commit=False)
        invitation.sender = self.sender
        invitation.save()
        invitation.send()
        return invitation

    def _invited_user_exists_error(self, email):
        self.user = get_user_model().objects.filter(email__iexact=email).first()
        if self.user:
            error = forms.ValidationError(_("Cet utilisateur existe déjà."))
            self.add_error("email", error)

    def _extend_expiration_date_or_error(self, email):
        invitation = Invitation.objects.filter(email__iexact=email).first()
        if invitation:
            if invitation.has_expired:
                invitation.extend_expiration_date()
            else:
                error = forms.ValidationError(_("Cette personne a déjà été invitée."))
                self.add_error("email", error)


class BaseInvitationFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        """
        By default, BaseModelFormSet show the objects stored in the DB.
        See https://docs.djangoproject.com/en/3.0/topics/forms/modelforms/#changing-the-queryset
        """
        super().__init__(*args, **kwargs)
        self.queryset = Invitation.objects.none()


InvitationFormSet = modelformset_factory(
    Invitation, form=NewInvitationForm, formset=BaseInvitationFormSet, extra=1, max_num=30
)


class NewUserForm(SignupForm):
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
        self.email = invitation.email
        super(NewUserForm, self).__init__(*args, **kwargs)
        self.fields.pop("email")
        self.fields["first_name"].initial = invitation.first_name
        self.fields["last_name"].initial = invitation.last_name

    def save(self, request):
        self.cleaned_data["email"] = self.email
        DefaultAccountAdapter().stash_verified_email(request, self.email)
        user = super(NewUserForm, self).save(request)
        return user
