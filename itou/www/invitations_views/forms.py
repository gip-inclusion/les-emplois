from django import forms
from django.core.exceptions import ValidationError

from itou.invitations.models import EmployerInvitation, LaborInspectorInvitation, PrescriberWithOrgInvitation
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.forms import validate_francetravail_email
from itou.users.models import User


# FIXME(alaurent) Refactor these classes

########################################################################
##################### PrescriberWithOrg invitation #####################
########################################################################


class PrescriberWithOrgInvitationForm(forms.ModelForm):
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
            if not user.is_professional:
                error = forms.ValidationError("Cet utilisateur n'est pas un professionel.")
                self.add_error("email", error)
            else:
                user_is_member = self.organization.active_members.filter(email=user.email).exists()
                if user_is_member:
                    error = forms.ValidationError("Cette personne fait déjà partie de votre organisation.")
                    self.add_error("email", error)

    def clean_email(self):
        email = self.cleaned_data["email"]

        self._invited_user_exists_error(email)
        if self.organization.kind == PrescriberOrganizationKind.FT:
            validate_francetravail_email(email)
        return email

    def save(self, *args, **kwargs):
        invitation = super().save(commit=False)
        invitation.sender = self.sender
        invitation.organization = self.organization
        invitation.save()
        return invitation


class BaseInvitationFormSet(forms.BaseModelFormSet):
    def clean(self):
        """Checks that no two invitations have the same email."""
        if any(self.errors):
            return

        emails = []
        for form in self.forms:
            email = form.cleaned_data.get("email")
            if email in emails:
                raise ValidationError("Les collaborateurs doivent avoir des adresses e-mail différentes.")
            emails.append(email)


class BasePrescriberWithOrgInvitationFormSet(BaseInvitationFormSet):
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


#############################################################
###################### EmployerInvitation ##################
#############################################################


class EmployerInvitationForm(forms.ModelForm):
    class Meta:
        fields = ["first_name", "last_name", "email"]
        model = EmployerInvitation

    def __init__(self, sender, company, *args, **kwargs):
        self.sender = sender
        self.company = company
        super().__init__(*args, **kwargs)

    def _invited_user_exists_error(self, email):
        """
        An employer can only invite another employer to join his structure.
        """
        user = User.objects.filter(email__iexact=email).first()
        if user:
            if not user.is_professional:
                error = forms.ValidationError("Cet utilisateur n'est pas un professionel.")
                self.add_error("email", error)
            else:
                user_is_member = self.company.active_members.filter(email=user.email).exists()
                if user_is_member:
                    error = forms.ValidationError("Cette personne fait déjà partie de votre structure.")
                    self.add_error("email", error)

    def clean_email(self):
        email = self.cleaned_data["email"]
        self._invited_user_exists_error(email)
        return email

    def save(self, *args, **kwargs):
        invitation = super().save(commit=False)
        invitation.sender = self.sender
        invitation.company = self.company
        invitation.save()
        return invitation


class BaseEmployerInvitationFormSet(BaseInvitationFormSet):
    def __init__(self, *args, **kwargs):
        """
        By default, BaseModelFormSet show the objects stored in the DB.
        See https://docs.djangoproject.com/en/3.0/topics/forms/modelforms/#changing-the-queryset
        """
        super().__init__(*args, **kwargs)
        self.queryset = EmployerInvitation.objects.none()
        # Any access to `self.forms` must be performed after any access to `self.queryset`,
        # otherwise `self.queryset` will have no effect.
        # https://code.djangoproject.com/ticket/31879
        self.forms[0].empty_permitted = False


#############################################################
##################### LaborInspectorInvitation ##############
#############################################################


class LaborInspectorInvitationForm(forms.ModelForm):
    class Meta:
        fields = ["first_name", "last_name", "email"]
        model = LaborInspectorInvitation

    def __init__(self, sender, institution, *args, **kwargs):
        self.sender = sender
        self.institution = institution
        super().__init__(*args, **kwargs)

    def _invited_user_exists_error(self, email):
        """
        A labor inspector can only invite another labor inspector to join his structure.
        """
        user = User.objects.filter(email__iexact=email).first()
        if user:
            if not user.is_professional:
                error = forms.ValidationError("Cet utilisateur n'est pas un professionel.")
                self.add_error("email", error)
            else:
                user_is_member = self.institution.active_members.filter(email=user.email).exists()
                if user_is_member:
                    error = forms.ValidationError("Cette personne fait déjà partie de votre structure.")
                    self.add_error("email", error)

    def clean_email(self):
        email = self.cleaned_data["email"]
        self._invited_user_exists_error(email)
        return email

    def save(self, *args, **kwargs):
        invitation = super().save(commit=False)
        invitation.sender = self.sender
        invitation.institution = self.institution
        invitation.save()
        return invitation


class BaseLaborInspectorInvitationFormSet(BaseInvitationFormSet):
    def __init__(self, *args, **kwargs):
        """
        By default, BaseModelFormSet show the objects stored in the DB.
        See https://docs.djangoproject.com/en/3.0/topics/forms/modelforms/#changing-the-queryset
        """
        super().__init__(*args, **kwargs)
        self.queryset = LaborInspectorInvitation.objects.none()
        # Any access to `self.forms` must be performed after any access to `self.queryset`,
        # otherwise `self.queryset` will have no effect.
        # https://code.djangoproject.com/ticket/31879
        self.forms[0].empty_permitted = False
