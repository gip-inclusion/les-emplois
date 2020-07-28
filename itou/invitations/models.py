import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.shortcuts import get_object_or_404, reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _

from itou.utils.emails import get_email_message
from itou.utils.perms.user import KIND_JOB_SEEKER, KIND_PRESCRIBER, KIND_SIAE_STAFF
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)


class InvitationAbstract(models.Model):
    # String representing the account type to use when logging in.
    # f"reverse("account_login")?account_type={account_type}"
    SIGNIN_ACCOUNT_TYPE = None
    EXPIRATION_DAYS = 14
    GUEST_TYPE_JOB_SEEKER = KIND_JOB_SEEKER
    GUEST_TYPE_PRESCRIBER = KIND_PRESCRIBER
    GUEST_TYPE_PRESCRIBER_WITH_ORG = KIND_PRESCRIBER
    GUEST_TYPE_SIAE_STAFF = KIND_SIAE_STAFF
    GUEST_TYPES = [
        (GUEST_TYPE_JOB_SEEKER, _("Candidat")),
        (GUEST_TYPE_PRESCRIBER, _("Prescripteur sans organisation")),
        (GUEST_TYPE_PRESCRIBER_WITH_ORG, _("Prescripteur membre d'une organisation")),
        (GUEST_TYPE_SIAE_STAFF, _("Employeur")),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(verbose_name=_("E-mail"))
    first_name = models.CharField(verbose_name=_("Prénom"), max_length=255)
    last_name = models.CharField(verbose_name=_("Nom"), max_length=255)
    sent = models.BooleanField(verbose_name=_("Envoyée"), default=False)

    accepted = models.BooleanField(verbose_name=_("Acceptée"), default=False)
    accepted_at = models.DateTimeField(verbose_name=_("Date d'acceptation"), blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(verbose_name=_("Date d'envoi"), blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        abstract = True

    @classmethod
    def get_model_from_string(cls, model_string):
        """
        Retrieve the model to use depending on a string.
        Usage:
        invitation_model = Invitation.get_model_from_string("siae_staff")
        invitation_model.objects.count()
        """
        if model_string == cls.GUEST_TYPE_SIAE_STAFF:
            return SiaeStaffInvitation
        elif model_string == cls.GUEST_TYPE_PRESCRIBER_WITH_ORG:
            return PrescriberWithOrgInvitation
        raise TypeError

    def __str__(self):
        return f"{self.email}"

    @property
    def acceptance_link(self):
        """
        Link present in the invitation email.
        """
        raise NotImplementedError

    @property
    def expiration_date(self):
        return self.sent_at + relativedelta(days=self.EXPIRATION_DAYS)

    @property
    def has_expired(self):
        return self.expiration_date <= timezone.now()

    @property
    def can_be_accepted(self):
        return not self.accepted and not self.has_expired and self.sent

    def accept(self):
        self.accepted = True
        self.accepted_at = timezone.now()
        self.accepted_notif_sender()
        self.save()

    def extend_expiration_date(self):
        self.sent_at = timezone.now()
        self.save()

    def send(self):
        self.sent = True
        self.sent_at = timezone.now()
        self.send_invitation()
        self.save()

    def set_guest_type(self, user):
        user.is_job_seeker = True
        return user

    def accepted_notif_sender(self):
        self.email_accepted_notif_sender.send()

    def send_invitation(self):
        self.email_invitation.send()

    # Emails
    @property
    def email_accepted_notif_sender(self):
        """
        Emails content depend on the guest kind.
        """
        raise NotImplementedError

    @property
    def email_invitation(self):
        """
        Emails content depend on the guest kind.
        """
        raise NotImplementedError


class PrescriberWithOrgInvitation(InvitationAbstract):
    SIGNIN_ACCOUNT_TYPE = "prescriber"
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Parrain ou marraine"),
        on_delete=models.CASCADE,
        related_name="prescriber_org_invitations",
    )
    organization = models.ForeignKey(
        "prescribers.PrescriberOrganization", on_delete=models.CASCADE, related_name="invitations"
    )

    class Meta:
        verbose_name = "Invitation prescripteurs"
        verbose_name_plural = "Invitations prescripteurs"

    @property
    def acceptance_link(self):
        kwargs = {"invitation_id": self.pk}
        signup_kwargs = {"invitation_type": self.GUEST_TYPE_PRESCRIBER_WITH_ORG, **kwargs}
        args = {"redirect_to": reverse("invitations_views:join_prescriber_organization", kwargs=kwargs)}
        acceptance_path = "{}?{}".format(
            reverse("invitations_views:new_user", kwargs=signup_kwargs), urlencode(args, True)
        )
        return get_absolute_url(acceptance_path)

    def accept(self):
        super().accept()
        self.email_accepted_notif_organization_members.send()

    def add_invited_user_to_organization(self):
        user = get_user_model().objects.get(email=self.email)
        self.organization.members.add(user)
        user.save()

    def guest_can_join_organization(self, request):
        user = get_object_or_404(get_user_model(), email=self.email)
        return user == request.user and user.is_prescriber and not user.prescriberorganization_set.exists()

    def set_guest_type(self, user):
        user.is_prescriber = True
        return user

    # Emails
    @property
    def email_accepted_notif_organization_members(self):
        members = self.organization.members.exclude(email__in=[self.sender.email, self.email])
        to = [member.email for member in members]
        context = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "establishment_name": self.organization.display_name,
            "sender": self.sender,
        }
        subject = "invitations_views/email/accepted_notif_establishment_members_subject.txt"
        body = "invitations_views/email/accepted_notif_establishment_members_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_accepted_notif_sender(self):
        to = [self.sender.email]
        context = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "establishment_name": self.organization.display_name,
        }
        subject = "invitations_views/email/accepted_notif_sender_subject.txt"
        body = "invitations_views/email/accepted_notif_establishment_sender_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_invitation(self):
        to = [self.email]
        context = {
            "acceptance_link": self.acceptance_link,
            "expiration_date": self.expiration_date,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "sender": self.sender,
            "org": self.organization,
        }
        subject = "invitations_views/email/invitation_establishment_subject.txt"
        body = "invitations_views/email/invitation_establishment_body.txt"
        return get_email_message(to, context, subject, body)


class SiaeStaffInvitation(InvitationAbstract):
    SIGNIN_ACCOUNT_TYPE = "siae"
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Parrain ou marraine"),
        on_delete=models.CASCADE,
        related_name="siae_invitations",
    )
    siae = models.ForeignKey("siaes.Siae", on_delete=models.CASCADE, related_name="invitations")

    class Meta:
        verbose_name = "Invitation employeur"
        verbose_name_plural = "Invitations employeurs"

    @property
    def acceptance_link(self):
        kwargs = {"invitation_id": self.pk}
        signup_kwargs = {"invitation_type": self.GUEST_TYPE_SIAE_STAFF, **kwargs}
        args = {"redirect_to": reverse("invitations_views:join_siae", kwargs=kwargs)}
        acceptance_path = "{}?{}".format(
            reverse("invitations_views:new_user", kwargs=signup_kwargs), urlencode(args, True)
        )
        return get_absolute_url(acceptance_path)

    def accept(self):
        super().accept()
        self.email_accepted_notif_siae_members.send()

    def add_invited_user_to_siae(self):
        user = get_user_model().objects.get(email=self.email)
        self.siae.members.add(user)
        user.save()

    def guest_can_join_siae(self, request):
        user = get_object_or_404(get_user_model(), email=self.email)
        return user == request.user and user.is_siae_staff

    def set_guest_type(self, user):
        user.is_siae_staff = True
        return user

    # Emails
    @property
    def email_accepted_notif_siae_members(self):
        members = self.siae.members.exclude(email__in=[self.sender.email, self.email])
        to = [member.email for member in members]
        context = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "establishment_name": self.siae.display_name,
            "sender": self.sender,
        }
        subject = "invitations_views/email/accepted_notif_establishment_members_subject.txt"
        body = "invitations_views/email/accepted_notif_establishment_members_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_accepted_notif_sender(self):
        to = [self.sender.email]
        context = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "establishment_name": self.siae.display_name,
        }
        subject = "invitations_views/email/accepted_notif_sender_subject.txt"
        body = "invitations_views/email/accepted_notif_establishment_sender_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_invitation(self):
        to = [self.email]
        context = {
            "acceptance_link": self.acceptance_link,
            "expiration_date": self.expiration_date,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "sender": self.sender,
            "org": self.siae,
        }
        subject = "invitations_views/email/invitation_establishment_subject.txt"
        body = "invitations_views/email/invitation_establishment_body.txt"
        return get_email_message(to, context, subject, body)
