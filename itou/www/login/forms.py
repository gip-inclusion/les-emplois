from allauth.account.forms import LoginForm
from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from itou.openid_connect.errors import format_error_modal_content
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.www.invitations_views.helpers import accept_all_pending_invitations
from itou.www.login.constants import ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY


class FindExistingUserViaEmailForm(forms.Form):
    """
    Validates only the email field. Displays a modal to user if email not in use
    """

    email = forms.EmailField(
        label="Adresse e-mail",
        required=True,
        widget=forms.TextInput(
            attrs={"type": "email", "placeholder": "adresse@email.fr", "autocomplete": "email", "autofocus": True}
        ),
    )

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data.get("email")
        self.user = User.objects.filter(email__iexact=email).first()
        if self.user is None:
            messages.error(
                self.request,
                format_error_modal_content(
                    mark_safe(
                        "<p>Cette adresse e-mail est inconnue de nos services.</p>"
                        "<p>Si vous êtes déjà inscrit(e), "
                        "assurez-vous de saisir correctement votre adresse e-mail.</p>"
                        "<p>Si vous n'êtes pas encore inscrit(e), "
                        "nous vous invitons à cliquer sur Inscription pour créer votre compte.</p>"
                    ),
                    reverse("signup:job_seeker_situation"),
                    "Inscription",
                ),
                extra_tags="modal login_failure email_does_not_exist",
            )
            raise ValidationError("Cette adresse e-mail est inconnue. Veuillez en saisir une autre, ou vous inscrire.")
        self.request.session[ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY] = email
        return email


class ItouLoginForm(LoginForm):
    # Hidden field allowing demo prescribers and employers to log in using the banner form
    demo_banner_account = forms.BooleanField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        user_email = kwargs.pop("user_email", None)
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs["placeholder"] = "**********"
        self.fields["password"].help_text = format_html(
            '<a href="{}" class="btn-link fs-sm">Mot de passe oublié ?</a>',
            reverse("account_reset_password"),
        )
        self.fields["login"].label = "Adresse e-mail"

        if user_email:
            self.fields["login"].initial = user_email
            self.fields["login"].widget.attrs["disabled"] = True
            self.data = self.data.dict() | {"login": user_email}
        else:
            self.fields["login"].widget.attrs["placeholder"] = "adresse@email.fr"
            self.fields["login"].widget.attrs["autofocus"] = True

    def clean(self):
        # Parent method performs authentication on form success.
        user = User.objects.filter(email=self.data["login"]).first()
        if (
            user
            and user.has_sso_provider
            # Bypass sso login error if we show the test account banner and the form received the hidden field value
            and not (self.cleaned_data.get("demo_banner_account") and settings.SHOW_DEMO_ACCOUNTS_BANNER)
            # TODO(alaurent): Update this behaviour on 2025/05 depending on if ProConnect has less issues
            # Allow ProConnect and Inclusion Connect users to bypass ProConnect if FORCE_PROCONNECT_LOGIN is False
            and (
                settings.FORCE_PROCONNECT_LOGIN
                or user.identity_provider not in [IdentityProvider.PRO_CONNECT, IdentityProvider.INCLUSION_CONNECT]
            )
        ):
            identity_provider = IdentityProvider(user.identity_provider)
            if identity_provider == IdentityProvider.INCLUSION_CONNECT:
                error_message = (
                    f"Votre compte est relié à {identity_provider.label}. "
                    "Merci de vous connecter avec ProConnect qui remplace ce service."
                )
            else:
                error_message = (
                    f"Votre compte est relié à {identity_provider.label}. Merci de vous connecter avec ce service."
                )
            raise forms.ValidationError(error_message)
        return super().clean()

    def login(self, request, redirect_url=None):
        ret = super().login(request=request, redirect_url=redirect_url)

        if request.user.is_authenticated and request.user.kind in [
            UserKind.PRESCRIBER,
            UserKind.EMPLOYER,
            UserKind.LABOR_INSPECTOR,
        ]:
            accept_all_pending_invitations(request)

        return ret
