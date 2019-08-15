from django.contrib.auth.decorators import login_required
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import render
from django.urls import reverse_lazy

from allauth.account.views import PasswordChangeView

from itou.users.decorators import perm_required


@login_required
@perm_required('job_seeker', 'prescriber', 'siae_staff')
def dashboard(request, template_name='account_itou/dashboard.html'):

    context = {}
    return render(request, template_name, context)


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """
    success_url = reverse_lazy('accounts:dashboard')


password_change = login_required(ItouPasswordChangeView.as_view())
