from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from itou.invitations.models import Invitation
from itou.www.invitations_views.forms import NewInvitationForm


def accept(request, invitation_id):
    try:
        invitation = Invitation.objects.get(pk=invitation_id)
    except Invitation.DoesNotExist:
        raise Http404(_("Aucune invitation n'a été trouvée."))

    if invitation.can_be_accepted:
        user = get_user_model().objects.filter(email=invitation.email)
        if not user:
            next_step = redirect("signup:from_invitation", invitation_id=invitation_id)
        else:
            messages.error(request, _("Vous comptez déjà parmi les membres de notre site."))
            context = {"invitation": invitation}
            next_step = render(request, "invitations_views/accept.html", context=context)
    else:
        context = {"invitation": invitation}
        next_step = render(request, "invitations_views/accept.html", context=context)

    return next_step


@login_required
def create(request, template_name="invitations_views/create.html"):
    form = NewInvitationForm(data=request.POST or None)

    if request.POST and form.is_valid():
        form.save(request)
        messages.success(request, _("Invitation envoyée avec succès !"))

    context = {"form": form}

    return render(request, template_name, context)
