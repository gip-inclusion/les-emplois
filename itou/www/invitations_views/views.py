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

    if invitation.has_expired:
        messages.error(
            request,
            _(
                """
            Cette invitation est expirée. Merci de contacter la personne
            qui vous a invité(e) afin d'en recevoir une nouvelle.
        """
            ),
        )

    if messages.get_messages(request):
        context = {"invitation": invitation}
        return render(request, "invitations_views/accept.html", context=context)

    return redirect("signup:from_invitation", invitation_id=invitation_id)
