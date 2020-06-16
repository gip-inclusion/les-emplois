from allauth.account.adapter import DefaultAccountAdapter
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext as __

from itou.invitations.models import Invitation
from itou.www.invitations_views.forms import InvitationFormSet, NewUserForm


def accept(request, invitation_id, template_name="invitations_views/accept.html"):
    try:
        invitation = Invitation.objects.get(pk=invitation_id)
    except Invitation.DoesNotExist:
        raise Http404(_("Aucune invitation n'a été trouvée."))

    context = {"invitation": invitation}
    next_step = None

    if invitation.can_be_accepted:
        user = get_user_model().objects.filter(email=invitation.email)
        if not user:
            form = NewUserForm(data=request.POST or None, invitation=invitation)
            context["form"] = form
            if form.is_valid():
                user = form.save(request)
                invitation.accept()
                DefaultAccountAdapter().login(request, user)
                next_step = redirect("dashboard:index")
        else:
            messages.error(request, _("Vous comptez déjà parmi les membres de notre site."))

    return next_step or render(request, template_name, context=context)


@login_required
def create(request, template_name="invitations_views/create.html"):
    form_kwargs = {"sender": request.user}
    formset = InvitationFormSet(data=request.POST or None, form_kwargs=form_kwargs)
    expiration_date = timezone.now() + relativedelta(days=Invitation.EXPIRATION_DAYS)

    if request.POST:
        if formset.is_valid():
            formset.save()
            count = len(formset.forms)

            message = __("Invitation envoyée avec succès.", "Invitations envoyées avec succès.", count) % {
                "count": count
            }

            messages.success(request, message)
            formset = InvitationFormSet(form_kwargs=form_kwargs)

    pending_invitations = request.user.invitations.filter(accepted=False)
    context = {"formset": formset, "expiration_date": expiration_date, "pending_invitations": pending_invitations}

    return render(request, template_name, context)
