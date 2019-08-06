from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.generic import TemplateView

from itou.accounts import views


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
    # /accounts/password/change/                        account_change_password
    # /accounts/password/reset/                         account_reset_password
    # /accounts/password/reset/done/                    account_reset_password_done
    # /accounts/password/reset/key/<uidb36>-<key>/      account_reset_password_from_key
    # /accounts/password/reset/key/done/                account_reset_password_from_key_done
    # /accounts/password/set/                           account_set_password
    # /accounts/social/connections/                     socialaccount_connections
    # /accounts/social/login/cancelled/                 socialaccount_login_cancelled
    # /accounts/social/login/error/                     socialaccount_login_error

    # Override allauth signup URL.
    # /accounts/signup/                                 account_signup
    # We don't want any user to be able to signup using the default allauth `signup` url
    # because we have multiple specific signup processes for different kind of users.
    re_path(r'^signup/$', TemplateView.as_view(template_name='account_itou/signup.html'), name='account_signup'),

    path('signup/prescriber', views.PrescriberSignupView.as_view(), name='prescriber_signup'),
    path('signup/siae', views.SiaeSignupView.as_view(), name='siae_signup'),
    path('signup/job_seeker', views.JobSeekerSignupView.as_view(), name='job_seeker_signup'),

]
