from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse_lazy

from allauth.account.views import PasswordChangeView


@login_required
def dashboard(request, template_name="dashboard/dashboard.html"):

    context = {}
    return render(request, template_name, context)


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """

    success_url = reverse_lazy("dashboard:index")


password_change = login_required(ItouPasswordChangeView.as_view())
