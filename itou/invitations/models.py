import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.shortcuts import get_object_or_404, reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.users.models import User
from itou.utils.emails import get_email_message
from itou.utils.perms.user import KIND_JOB_SEEKER, KIND_LABOR_INSPECTOR, KIND_PRESCRIBER, KIND_SIAE_STAFF
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)


class InvitationQuerySet(models.QuerySet):
    @property
    def valid_lookup(self):
        expiration_dt = timezone.now() - relativedelta(days=self.model.EXPIRATION_DAYS)
        return models.Q(sent_at__gte=expiration_dt)

    def valid(self):
        return self.filter(self.valid_lookup)

    def expired(self):
        return self.exclude(self.valid_lookup)

    def pending(self):
        return self.valid().filter(accepted=False).order_by("sent_at")


class InvitationAbstract(models.Model):
    # String representing the account type to use when logging in.
    # reverse(f"login:{account_type}")
    SIGNIN_ACCOUNT_TYPE = ""
    EXPIRATION_DAYS = 14
    GUEST_TYPE_JOB_SEEKER = KIND_JOB_SEEKER
    GUEST_TYPE_PRESCRIBER = KIND_PRESCRIBER
    GUEST_TYPE_PRESCRIBER_WITH_ORG = KIND_PRESCRIBER
    GUEST_TYPE_SIAE_STAFF = KIND_SIAE_STAFF
    GUEST_TYPE_LABOR_INSPECTOR = KIND_LABOR_INSPECTOR
    GUEST_TYPES = [
        (GUEST_TYPE_JOB_SEEKER, "Candidat"),
        (GUEST_TYPE_PRESCRIBER, "Prescripteur sans organisation"),
        (GUEST_TYPE_PRESCRIBER_WITH_ORG, "Prescripteur membre d'une organisation"),
        (GUEST_TYPE_SIAE_STAFF, "Employeur"),
        (GUEST_TYPE_LABOR_INSPECTOR, "Inspecteur du travail (DGEFP, DDETS, DREETS)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(verbose_name="E-mail")
    first_name = models.CharField(verbose_name="Prénom", max_length=255)
    last_name = models.CharField(verbose_name="Nom", max_length=255)
    sent = models.BooleanField(verbose_name="Envoyée", default=False)

    accepted = models.BooleanField(verbose_name="Acceptée", default=False)
    accepted_at = models.DateTimeField(verbose_name="Date d'acceptation", blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(verbose_name="Date d'envoi", blank=True, null=True, db_index=True)

    objects = models.Manager.from_queryset(InvitationQuerySet)()

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
        elif model_string == cls.GUEST_TYPE_LABOR_INSPECTOR:
            return LaborInspectorInvitation
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
        self.save()
        self.accepted_notif_sender()

    def send(self):
        self.sent = True
        self.sent_at = timezone.now()
        self.save()
        self.send_invitation()

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
        verbose_name="Parrain ou marraine",
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

    def add_invited_user_to_organization(self):
        user = User.objects.get(email=self.email)
        self.organization.members.add(user)
        user.save()
        # We must be able to invite a former member of this prescriber organization
        # however `members.add()` does not update membership status if it already exists
        if user not in self.organization.active_members:
            membership = user.prescribermembership_set.get(is_active=False, organization=self.organization)
            membership.is_active = True
            membership.save()

    def guest_can_join_organization(self, request):
        user = get_object_or_404(User, email=self.email)
        return user == request.user and user.is_prescriber

    def set_guest_type(self, user):
        user.is_prescriber = True
        return user

    # Emails
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
            "establishment": self.organization,
        }
        subject = "invitations_views/email/invitation_establishment_subject.txt"
        body = "invitations_views/email/invitation_establishment_body.txt"
        return get_email_message(to, context, subject, body)


class SiaeStaffInvitation(InvitationAbstract):
    SIGNIN_ACCOUNT_TYPE = "siae_staff"
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Parrain ou marraine",
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

    def add_invited_user_to_siae(self):
        user = User.objects.get(email=self.email)
        self.siae.members.add(user)
        user.save()
        # We must be able to invite a former member of this SIAE
        # however `members.add()` does not update membership status if it already exists
        if user not in self.siae.active_members:
            membership = user.siaemembership_set.get(is_active=False, siae=self.siae)
            membership.is_active = True
            membership.save()

    def guest_can_join_siae(self, request):
        user = get_object_or_404(User, email=self.email)
        return user == request.user and user.is_siae_staff

    def set_guest_type(self, user):
        user.is_siae_staff = True
        return user

    # Emails
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
            "establishment": self.siae,
        }
        subject = "invitations_views/email/invitation_establishment_subject.txt"
        body = "invitations_views/email/invitation_establishment_body.txt"
        return get_email_message(to, context, subject, body)


class LaborInspectorInvitation(InvitationAbstract):
    SIGNIN_ACCOUNT_TYPE = "labor_inspector"
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Parrain ou marraine",
        on_delete=models.CASCADE,
        related_name="institution_invitations",
    )
    institution = models.ForeignKey(
        "institutions.Institution", on_delete=models.CASCADE, related_name="labor_inspectors_invitations"
    )

    class Meta:
        verbose_name = "Invitation inspecteurs du travail"
        verbose_name_plural = "Invitations inspecteurs du travail"

    @property
    def acceptance_link(self):
        kwargs = {"invitation_id": self.pk, "invitation_type": self.GUEST_TYPE_LABOR_INSPECTOR}
        signup_kwargs = {"invitation_type": self.GUEST_TYPE_LABOR_INSPECTOR, **kwargs}
        args = {"redirect_to": reverse("invitations_views:join_institution", kwargs=kwargs)}
        acceptance_path = "{}?{}".format(
            reverse("invitations_views:new_user", kwargs=signup_kwargs), urlencode(args, True)
        )
        return get_absolute_url(acceptance_path)

    def add_invited_user_to_institution(self):
        user = User.objects.get(email=self.email)
        self.institution.members.add(user)
        user.save()
        # We must be able to invite a former member of this institution
        # however `members.add()` does not update membership status if it already exists
        if user not in self.institution.active_members:
            membership = user.institutionmembership_set.get(is_active=False, institution=self.institution)
            membership.is_active = True
            membership.save()

    def guest_can_join_institution(self, request):
        user = get_object_or_404(User, email=self.email)
        return user == request.user and user.is_labor_inspector

    def set_guest_type(self, user):
        user.is_labor_inspector = True
        return user

    # Emails
    @property
    def email_accepted_notif_sender(self):
        to = [self.sender.email]
        context = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "establishment_name": self.institution.display_name,
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
            "establishment": self.institution,
        }
        subject = "invitations_views/email/invitation_establishment_subject.txt"
        body = "invitations_views/email/invitation_establishment_body.txt"
        return get_email_message(to, context, subject, body)
