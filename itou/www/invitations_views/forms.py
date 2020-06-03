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


class BaseInvitationFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        """
        By default, BaseModelFormSet show the objects
        stored in the DB.
        See https://docs.djangoproject.com/en/3.0/topics/forms/modelforms/#changing-the-queryset
        """
        super().__init__(*args, **kwargs)
        self.queryset = Invitation.objects.none()

    def add_form(self, sender, **kwargs):
        """
        Adding a form to a formset is a real hassle
        that does not seem to bother the Django team.
        https://code.djangoproject.com/ticket/21596
        """
        self.forms.append(self._construct_form(self.total_form_count(), sender=sender, **kwargs))
        self.forms[-1].is_bound = False
        self.data = self.data.copy()
        total_forms = self.management_form.cleaned_data["TOTAL_FORMS"] + 1
        self.data[f'{self.management_form.prefix}-{"TOTAL_FORMS"}'] = total_forms
        self.management_form.data = self.management_form.data.copy()
        self.management_form.data[f'{self.management_form.prefix}-{"TOTAL_FORMS"}'] = total_forms


InvitationFormSet = modelformset_factory(Invitation, form=NewInvitationForm, formset=BaseInvitationFormSet, extra=1)
