from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext as __

from itou.invitations.models import Invitation
from itou.www.invitations_views.forms import InvitationFormSet


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
    base_url = request.build_absolute_uri("/")[:-1]
    form_kwargs = {"sender": request.user, "acceptance_link_base_url": base_url}
    formset = InvitationFormSet(data=request.POST or None, form_kwargs=form_kwargs)
    add_form = request.GET.get("add_form")
    expiration_date = timezone.now() + relativedelta(Invitation.EXPIRATION_DAYS)

    if add_form:
        formset.add_form(**form_kwargs)

    if request.POST:
        if formset.is_valid():
            # Validate the form even if the user only wants to add a row
            # to inform him of any possible error.
            if not add_form:
                formset.save()
                count = len(formset.forms)

                message = __("Invitation envoyée avec succès.", "Invitations envoyées avec succès.", count) % {
                    "count": count
                }

                messages.success(request, message)
                formset = InvitationFormSet(form_kwargs=form_kwargs)

    context = {"formset": formset, "expiration_date": expiration_date}

    return render(request, template_name, context)
