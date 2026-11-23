from django.http import Http404
from django.shortcuts import render

from itou.utils.perms.utils import can_view_personal_information
from itou.utils.readonly import readonly_view
from itou.www.next_steps_views.access import can_view_next_steps
from itou.www.next_steps_views.actions import (
    Group,
    describe_job_seekers,
    done_today,
    expected_actions,
    group_actions,
)


@readonly_view
def todo(request, template_name="next_steps/todo.html"):
    """« À faire »: the actions expected from the signed-in professional, by urgency."""
    if not can_view_next_steps(request):
        raise Http404

    actions = expected_actions(request)
    describe_job_seekers(actions, lambda job_seeker: can_view_personal_information(request, job_seeker))
    done = done_today(request)
    describe_job_seekers(done, lambda job_seeker: can_view_personal_information(request, job_seeker))
    context = {
        "groups": group_actions(actions),
        "pressing_count": sum(action.group != Group.WATCH for action in actions),
        "done_today": done,
        "matomo_custom_title": "Prochaines étapes : à faire",
    }
    return render(request, template_name, context)
