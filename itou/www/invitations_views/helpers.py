from django.contrib import messages
from django.core.exceptions import PermissionDenied

from itou.invitations.models import EmployerInvitation, LaborInspectorInvitation, PrescriberWithOrgInvitation


def handle_invitation(invitation, request):
    if not invitation.guest_can_join(request):
        raise PermissionDenied()

    if isinstance(invitation, EmployerInvitation) and not invitation.company.is_active:
        messages.error(request, "Cette structure n'est plus active.")
        return False

    if invitation.can_be_accepted:
        invitation.add_invited_user()
        invitation.accept()
        messages.success(request, f"Vous êtes désormais membre de l'organisation {invitation.target.display_name}.")
        return True

    messages.error(request, "Ce lien n'est plus valide.")
    return False


def accept_all_pending_invitations(request):
    if not request.user.is_authenticated:
        return False

    invitation_models = [PrescriberWithOrgInvitation, EmployerInvitation, LaborInspectorInvitation]

    accepted_invitations = []
    for InvitationModel in invitation_models:
        for invitation in InvitationModel.objects.pending().filter(email=request.user.email):
            if handle_invitation(invitation, request):
                accepted_invitations.append(invitation)
    return accepted_invitations
