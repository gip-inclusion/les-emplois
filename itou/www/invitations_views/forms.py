from django import forms
from django.forms.models import modelformset_factory
from django.contrib.auth import get_user_model
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
        self.user = get_user_model().objects.filter(email__iexact=email).first()
        if self.user:
            error = forms.ValidationError(_("Cet utilisateur existe déjà."))
            self.add_error("email", error)

        invitation = Invitation.objects.filter(email__iexact=email).first()
        if invitation:
            if invitation.has_expired:
                invitation.extend_expiration_date()
            else:
                error = forms.ValidationError(_("Cette personne a déjà été invitée."))
                self.add_error("email", error)

        return email

    def save(self, *args, **kwargs):
        invitation = super(NewInvitationForm, self).save(commit=False)
        invitation.sender = self.sender
        invitation.save()
        invitation.send()
        return invitation

InvitationFormSet = modelformset_factory(Invitation, form=NewInvitationForm, extra=1)
