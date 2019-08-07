from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.generic import TemplateView

from itou.accounts.views import signup as signup_views
from itou.accounts.views import dashboard as dashboard_views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = 'accounts'

urlpatterns = [

    # allauth URLs.
    # /accounts/confirm-email/                          account_email_verification_sent
    # /accounts/confirm-email/<key>/                    account_confirm_email
    # /accounts/email/                                  account_email
    # /accounts/inactive/                               account_inactive
    # /accounts/login/                                  account_login
    # /accounts/logout/                                 account_logout
    # /accounts/password/reset/                         account_reset_password
    # /accounts/password/reset/done/                    account_reset_password_done
    # /accounts/password/reset/key/<uidb36>-<key>/      account_reset_password_from_key
    # /accounts/password/reset/key/done/                account_reset_password_from_key_done
    # /accounts/password/set/                           account_set_password
    # /accounts/social/connections/                     socialaccount_connections
    # /accounts/social/login/cancelled/                 socialaccount_login_cancelled
    # /accounts/social/login/error/                     socialaccount_login_error

    # Override allauth `account_signup` URL.
    # /accounts/signup/                                 account_signup
    # We don't want any user to be able to signup using the default allauth `signup` url
    # because we have multiple specific signup processes for different kind of users.
    re_path(r'^signup/$', TemplateView.as_view(template_name='account_itou/signup.html')),

    # Override allauth `account_change_password` URL.
    # /accounts/password/change/                        account_change_password
    # https://github.com/pennersr/django-allauth/issues/468
    re_path(r'^password/change/$', dashboard_views.password_change),

    path('signup/prescriber', signup_views.PrescriberSignupView.as_view(), name='prescriber_signup'),
    path('signup/siae', signup_views.SiaeSignupView.as_view(), name='siae_signup'),
    path('signup/job_seeker', signup_views.JobSeekerSignupView.as_view(), name='job_seeker_signup'),

    path('dashboard', dashboard_views.dashboard, name='dashboard'),

]
