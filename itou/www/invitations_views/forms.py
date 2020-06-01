from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _, gettext_lazy

from itou.invitations.models import Invitation


class NewInvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"]
        self.user = get_user_model().objects.filter(email__iexact=email).first()
        if self.user:
            error = forms.ValidationError(_("Cet utilisateur existe déjà."))
            self.add_error("email", error)
        return email

    def clean(self):
        email = self.cleaned_data["email"]
        invitation = Invitation.objects.filter(email__iexact=email).first()
        if invitation:
            if invitation.has_expired:
                invitation.extend_expiration_date()
            else:
                error = forms.ValidationError(_("Cette personne a déjà été invitée."))
                self.add_error("email", error)
        return self.cleaned_data

    def save(self, request, *args, **kwargs):
        invitation = super().save(commit=False)
        invitation.sender = request.user
        invitation.save()
        invitation.send()
        return invitation
