from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from itou.gps.models import FollowUpGroup


@login_required
def my_groups(request, template_name="gps/my_groups.html"):

    current_user = request.user
    groups = FollowUpGroup.objects.filter(members=current_user).all()

    context = {"groups": groups}

    return render(request, template_name, context)
