from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from itou.invitations.models import Invitation


def accept(request, invitation_id):
    try:
        invitation = Invitation.objects.get(pk=invitation_id)
    except Invitation.DoesNotExist:
        raise Http404(_("Aucune invitation n'a été trouvée."))

    if invitation.can_be_accepted:
        next_step = redirect("signup:from_invitation", invitation_id=invitation_id)
    else:
        context = {"invitation": invitation}
        next_step = render(request, "invitations_views/accept.html", context=context)

    return next_step
