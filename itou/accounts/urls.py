from django.urls import path, re_path
from django.views.generic import RedirectView

from itou.accounts import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = 'accounts'

urlpatterns = [

    # Override the allauth `signup` url.
    re_path(r'^signup/$', RedirectView.as_view(pattern_name='accounts:prescriber_signup', permanent=False)),

    path('signup/prescriber', views.PrescriberSignupView.as_view(), name='prescriber_signup'),

]
