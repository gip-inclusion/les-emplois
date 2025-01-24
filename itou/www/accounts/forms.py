from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.password_validation import MinimumLengthValidator, validate_password
from django.core.exceptions import ValidationError


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
