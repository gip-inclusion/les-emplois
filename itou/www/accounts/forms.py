from urllib.parse import quote

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.password_validation import MinimumLengthValidator, validate_password
from django.core.exceptions import ValidationError
from django.urls import reverse

from itou.emails.models import EmailAddress
from itou.users.models import User
from itou.users.notifications import PasswordResetKeyNotification
from itou.utils.emails import get_email_message, send_email_messages
from itou.utils.tokens import EmailAwarePasswordResetTokenGenerator
from itou.utils.urls import get_absolute_url


class PasswordVerificationMixin:
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if (password1 and password2) and password1 != password2:
            self.add_error("password2", "Vous devez saisir deux fois le même mot de passe.")
        return cleaned_data


# TODO: investigate if you can remove the custom password fields and use Django's defaults
class PasswordField(forms.CharField):
    def __init__(self, *args, **kwargs):
        kwargs["widget"] = forms.PasswordInput(attrs={"placeholder": kwargs.get("label")})
        autocomplete = kwargs.pop("autocomplete", None)
        if autocomplete is not None:
            kwargs["widget"].attrs["autocomplete"] = autocomplete
        super().__init__(*args, **kwargs)


class SetPasswordField(PasswordField):
    def __init__(self, *args, **kwargs):
        kwargs["autocomplete"] = "new-password"
        kwargs.setdefault("help_text", password_validation.password_validators_help_text_html())
        super().__init__(*args, **kwargs)
        self.user = None

    def clean(self, value):
        value = super().clean(value)
        MinimumLengthValidator(settings.PASSWORD_MIN_LENGTH).validate(value)
        validate_password(value, self.user)
        return value


class UserForm(forms.Form):
    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)


class ChangePasswordForm(PasswordVerificationMixin, UserForm):
    oldpassword = PasswordField(label="Mot de passe actuel", autocomplete="current-password")
    password1 = SetPasswordField(label="Nouveau mot de passe")
    password2 = PasswordField(label="Nouveau mot de passe (confirmation)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].user = self.user

    def clean_oldpassword(self):
        if not self.user.check_password(self.cleaned_data.get("oldpassword")):
            raise ValidationError("Merci d'indiquer votre mot de passe actuel.", code="enter_current_password")
        return self.cleaned_data["oldpassword"]

    def save(self):
        self.user.set_password(self.cleaned_data["password1"])
        self.user.save()


class ResetPasswordForm(forms.Form):
    email = forms.EmailField(
        label="E-mail",
        required=True,
        widget=forms.TextInput(
            attrs={
                "type": "email",
                "placeholder": "Adresse e-mail",
                "autocomplete": "email",
            }
        ),
    )

    def user_does_not_exist(self):
        # Send email to intended recipient, and raise a ValidationError.
        send_email_messages(
            [
                get_email_message(
                    (self.cleaned_data["email"],),
                    {
                        "site_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/",
                        "signup_url": get_absolute_url(reverse("signup:choose_user_kind")),
                    },
                    "account/email/unknown_account_subject.txt",
                    "account/email/unknown_account_message.txt",
                )
            ]
        )
        raise ValidationError("Cette adresse e-mail n'est pas associée à un compte utilisateur", code="unknown_email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        try:
            # TODO: allauth would return an unknown email error if the email wasn't verified and the user not active.
            # Seek feedback but we probably want to allow the user to reset their password,
            # and insodoing confirm their email address?
            self.user = EmailAddress.objects.get(email=email).user
        except EmailAddress.DoesNotExist:
            self.user_does_not_exist()
        return self.cleaned_data["email"]

    def save(self, request, **kwargs):
        if not self.user:
            self.user_does_not_exist()

        # Send the password reset email.
        uid = self.user.pk_to_url_str
        key = quote(EmailAwarePasswordResetTokenGenerator().make_token(self.user))

        url = get_absolute_url(reverse("accounts:account_reset_password_from_key", kwargs={"uidb36": uid, "key": key}))

        PasswordResetKeyNotification(self.user, password_reset_url=url).send()


class ResetPasswordKeyForm(PasswordVerificationMixin, forms.Form):
    password1 = SetPasswordField(label="Nouveau mot de passe")
    password2 = PasswordField(label="Nouveau mot de passe (confirmation)")

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.temp_key = kwargs.pop("temp_key", None)
        super().__init__(*args, **kwargs)
        self.fields["password1"].user = self.user

    def save(self):
        self.user.set_password(self.cleaned_data["password1"])
        self.user.save()


class UserTokenForm(forms.Form):
    uidb36 = forms.CharField()
    key = forms.CharField()

    reset_user = None
    invalid_password_reset_message = "Le jeton de réinitialisation de mot de passe est invalide."
    invalid_password_reset_code = "invalid_password_reset"

    def _get_user(self, uidb36):
        try:
            pk = User.url_str_to_pk(uidb36)
            return User.objects.get(pk=pk)
        except (ValueError, User.DoesNotExist):
            return None

    def clean(self):
        cleaned_data = super().clean()

        uidb36 = cleaned_data.get("uidb36", None)
        key = cleaned_data.get("key", None)
        if not key:
            raise ValidationError(self.invalid_password_reset_message, code=self.invalid_password_reset_code)

        self.reset_user = self._get_user(uidb36)
        if self.reset_user is None or not EmailAwarePasswordResetTokenGenerator().check_token(self.reset_user, key):
            raise ValidationError(self.invalid_password_reset_message, code=self.invalid_password_reset_code)

        return cleaned_data
