from django.contrib.auth.decorators import login_not_required
from django.urls import path, re_path, reverse_lazy
from django.views.generic import RedirectView

from itou.www.accounts import views as account_views
from itou.www.login import views as login_views
from itou.www.logout import views as logout_views
from itou.www.signup import views as signup_views


app_name = "accounts"

urlpatterns = [
    # TODO(calum): temporary redirect for deployment, can be removed shortly after going live
    path(
        "signup",
        login_not_required(RedirectView.as_view(url=reverse_lazy("signup:choose_user_kind"))),
        name="account_signup",
    ),
    path("login", login_views.ItouLoginView.as_view(), name="account_login"),
    path("logout", logout_views.LogoutView.as_view(), name="account_logout"),
    path("inactive", account_views.AccountInactiveView.as_view(), name="account_inactive"),
    path("password/change", account_views.ItouPasswordChangeView.as_view(), name="account_change_password"),
    # Avoid user enumeration via password reset page.
    path("password/reset", signup_views.ItouPasswordResetView.as_view(), name="account_reset_password"),
    path(
        "password/reset/done/",
        account_views.PasswordResetDoneView.as_view(),
        name="account_reset_password_done",
    ),
    re_path(
        r"^password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
        signup_views.ItouPasswordResetFromKeyView.as_view(),
        name="account_reset_password_from_key",
    ),
    path(
        "confirm-email/",
        account_views.EmailVerificationSentView.as_view(),
        name="account_email_verification_sent",
    ),
    re_path(
        r"^confirm-email/(?P<key>[-:\w]+)/$",
        account_views.ConfirmEmailView.as_view(),
        name="account_confirm_email",
    ),
    # NOTE: left out reauthenticate, email (edit) views
    # NOTE: left out password set view. We set password during registration, so it shouldn't be necessary.
]
