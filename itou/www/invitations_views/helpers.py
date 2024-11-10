from django.contrib import messages
from django.core.exceptions import PermissionDenied

from itou.invitations.models import EmployerInvitation, LaborInspectorInvitation, PrescriberWithOrgInvitation
from itou.users.enums import UserKind


def handle_prescriber_intivation(invitation, request):
    if not invitation.guest_can_join_organization(request):
        raise PermissionDenied()

    if invitation.can_be_accepted:
        invitation.add_invited_user_to_organization()
        # Send an email after the model changes
        invitation.accept()
        messages.success(
            request, f"Vous êtes désormais membre de l'organisation {invitation.organization.display_name}."
        )
    elif not invitation.accepted_at:
        messages.error(request, "Cette invitation n'est plus valide.")


def handle_employer_invitation(invitation, request):
    if not invitation.guest_can_join_company(request):
        raise PermissionDenied()

    if not invitation.company.is_active:
        messages.error(request, "Cette structure n'est plus active.")
    elif invitation.can_be_accepted:
        invitation.add_invited_user_to_company()
        invitation.accept()
        messages.success(request, f"Vous êtes désormais membre de la structure {invitation.company.display_name}.")
    elif not invitation.accepted_at:
        messages.error(request, "Cette invitation n'est plus valide.")


def handle_labor_inspector_invitation(invitation, request):
    if not invitation.guest_can_join_institution(request):
        raise PermissionDenied()

    if invitation.can_be_accepted:
        invitation.add_invited_user_to_institution()
        invitation.accept()
        messages.success(
            request, f"Vous êtes désormais membre de l'organisation {invitation.institution.display_name}."
        )
    elif not invitation.accepted_at:
        messages.error(request, "Cette invitation n'est plus valide.")


def accept_all_pending_invitations(request):
    if not request.user.is_authenticated:
        return False

    MAPPING = {
        UserKind.PRESCRIBER: (PrescriberWithOrgInvitation, handle_prescriber_intivation),
        UserKind.EMPLOYER: (EmployerInvitation, handle_employer_invitation),
        UserKind.LABOR_INSPECTOR: (LaborInspectorInvitation, handle_labor_inspector_invitation),
    }

    InvitationModel, handle_invitation = MAPPING[request.user.kind]

    invitations = list(InvitationModel.objects.pending().filter(email=request.user.email))
    for invitation in invitations:
        handle_invitation(invitation, request)
    return invitations
