from django.urls import path, re_path
from django.views.generic import RedirectView

from itou.accounts import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = 'accounts'

urlpatterns = [

    # Override allauth signup URL.
    # We don't want any user to be able to signup using the default allauth `signup` url
    # because we have multiple specific signup processes for different kind of users.
    re_path(r'^signup/$', RedirectView.as_view(pattern_name='accounts:prescriber_signup', permanent=False)),

    path('signup/prescriber', views.PrescriberSignupView.as_view(), name='prescriber_signup'),
    path('signup/siae', views.SiaeSignupView.as_view(), name='siae_signup'),
    path('signup/job_seeker', views.JobSeekerSignupView.as_view(), name='job_seeker_signup'),

]
