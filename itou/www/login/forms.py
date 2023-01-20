from allauth.account.forms import LoginForm
from django import forms

from itou.users.models import User


class ItouLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs["placeholder"] = "**********"
        self.fields["login"].widget.attrs["placeholder"] = "adresse@email.fr"
        self.fields["login"].label = "Adresse e-mail"

    def clean(self):
        # Parent method performs authentication on form success.
        user = User.objects.filter(email=self.data["login"]).first()
        if user and user.has_sso_provider:
            identity_provider = user.get_identity_provider_display()
            error_message = f"Votre compte est relié à {identity_provider}. Merci de vous connecter avec ce service."
            raise forms.ValidationError(error_message)
        return super().clean()


class AccountMigrationForm(forms.Form):
    email = forms.CharField(label="Votre adresse e-mail")
