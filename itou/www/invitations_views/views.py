from django.http import Http404
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from itou.invitations.models import Invitation


def accept(request, encoded_invitation_id):
    try:
        Invitation.objects.get_from_encoded_pk(encoded_pk=encoded_invitation_id)
    except Invitation.DoesNotExist:
        raise Http404(_("Aucune invitation n'a été trouvée."))

    return redirect("signup:from_invitation", encoded_invitation_id=encoded_invitation_id)
