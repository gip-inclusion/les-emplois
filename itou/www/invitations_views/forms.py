from django import forms
from django.utils.translation import gettext as _, gettext_lazy

from itou.invitations.models import Invitation


class NewInvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["first_name", "last_name", "email"]

    def save(self, request, *args, **kwargs):
        invitation = super().save(commit=False)
        invitation.sender = request.user
        invitation.save()
        invitation.send()
        return invitation
