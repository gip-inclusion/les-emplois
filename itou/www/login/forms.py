from allauth.account.forms import LoginForm
from django import forms


class ItouLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs["placeholder"] = "**********"
        self.fields["login"].widget.attrs["placeholder"] = "adresse@email.fr"
        self.fields["login"].label = "Adresse e-mail"

    def clean(self):
        # Parent method authenticates user on form success.
        super().clean()
        if self.user and self.user.has_sso_provider:
            identity_provider = self.user.get_identity_provider_display()
            error_message = (
                f"Votre compte est relié à {identity_provider}. " "Merci de vous connecter avec ce service."
            )
        return self.cleaned_data
