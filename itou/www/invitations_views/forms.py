from allauth.account.adapter import get_adapter
from allauth.account.forms import SignupForm
from django import forms
from django.core.exceptions import ValidationError

from itou.invitations.models import EmployerInvitation, LaborInspectorInvitation, PrescriberWithOrgInvitation
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.forms import validate_francetravail_email
from itou.users.models import User


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
            if not user.is_prescriber:
                error = forms.ValidationError("Cet utilisateur n'est pas un prescripteur.")
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
            if not user.is_employer:
                error = forms.ValidationError("Cet utilisateur n'est pas un employeur.")
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
            if not user.is_labor_inspector:
                error = forms.ValidationError("Cet utilisateur n'est pas un inspecteur du travail.")
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


###############################################################
######################### Signup forms ########################
###############################################################


class NewUserInvitationForm(SignupForm):
    """
    Signup form shown when a user accepts an invitation.
    """

    first_name = forms.CharField(
        label="Prénom",
        max_length=User._meta.get_field("first_name").max_length,
        required=True,
        strip=True,
    )

    last_name = forms.CharField(
        label="Nom",
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

    def save(self, request):
        self.cleaned_data["email"] = self.email
        # Avoid django-allauth to call its own often failing `generate_unique_username`
        # function by forcing a username.
        self.cleaned_data["username"] = User.generate_unique_username()
        get_adapter().stash_verified_email(request, self.email)
        self.user_kind = self.invitation.USER_KIND
        return super().save(request)
