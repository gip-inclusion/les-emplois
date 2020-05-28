from django.http import Http404
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from itou.invitations.models import Invitation


def accept(request, invitation_id):
    try:
        Invitation.objects.get(pk=invitation_id)
    except Invitation.DoesNotExist:
        raise Http404(_("Aucune invitation n'a été trouvée."))

    return redirect("signup:from_invitation", invitation_id=invitation_id)
