from allauth.account.forms import LoginForm
from django import forms
from django.conf import settings

from itou.users.models import User


class ItouLoginForm(LoginForm):
    # Hidden field allowing demo prescriber and siae staff to log in using the banner form
    demo_banner_account = forms.BooleanField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs["placeholder"] = "**********"
        self.fields["login"].widget.attrs["placeholder"] = "adresse@email.fr"
        self.fields["login"].label = "Adresse e-mail"

    def clean(self):
        # Parent method performs authentication on form success.
        user = User.objects.filter(email=self.data["login"]).first()
        if (
            user
            and user.has_sso_provider
            # Bypass sso login error if we show the test account banner and the form received the hidden field value
            and not (self.cleaned_data.get("demo_banner_account") and settings.SHOW_TEST_ACCOUNTS_BANNER)
        ):
            identity_provider = user.get_identity_provider_display()
            error_message = f"Votre compte est relié à {identity_provider}. Merci de vous connecter avec ce service."
            raise forms.ValidationError(error_message)
        return super().clean()
