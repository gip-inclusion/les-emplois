from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from itou.gps.models import FollowUpGroup


@login_required
def my_groups(request, template_name="gps/my_groups.html"):

    current_user = request.user
    groups = (
        FollowUpGroup.objects.filter(members=current_user)
        .select_related("beneficiary")
        .prefetch_related("members")
        .all()
    )

    breadcrumbs = {
        "Mes groupes de suivi": reverse("gps:my_groups"),
    }

    context = {
        "breadcrumbs": breadcrumbs,
        "groups": groups,
    }

    return render(request, template_name, context)


@login_required
def join_group(request, template_name="gps/join_group.html"):

    breadcrumbs = {
        "Mes groupes de suivi": reverse("gps:my_groups"),
        "Rejoindre un groupe de suivi": reverse("gps:join_group"),
    }

    context = {"breadcrumbs": breadcrumbs}

    return render(request, template_name, context)
