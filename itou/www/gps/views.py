from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def my_groups(request, template_name="gps/my_groups.html"):
    context = {}

    return render(request, template_name, context)
