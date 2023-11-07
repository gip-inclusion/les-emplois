import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.shortcuts import get_object_or_404, reverse
from django.utils import timezone

from itou.users.enums import KIND_EMPLOYER, KIND_LABOR_INSPECTOR, KIND_PRESCRIBER, UserKind
from itou.users.models import User
from itou.utils.emails import get_email_message
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)


class InvitationQuerySet(models.QuerySet):
    @property
    def valid_lookup(self):
        # 1) `relativedelta(days=models.F("validity_days"))` raises TypeError exception,
        # see https://stackoverflow.com/questions/6158859/making-queries-using-f-and-timedelta-at-django
        # 2) `relativedelta(days=1) * models.F("validity_days")` still raises an exception
        # `django.db.utils.ProgrammingError: can't adapt type 'relativedelta'`
        # 3) getting rid of relativedelta and using dates directly is the only solution found so far
        # see https://stackoverflow.com/questions/56167142/django-orm-get-records-that-are-older-than-records-duration-days
        expiration_date = timezone.localdate() - models.F("validity_days")
        return models.Q(sent_at__date__gt=expiration_date)

    def valid(self):
        return self.filter(self.valid_lookup)

    def expired(self):
        return self.exclude(self.valid_lookup)

    def pending(self):
        return self.valid().filter(accepted=False).order_by("sent_at")


class InvitationAbstract(models.Model):
    DEFAULT_VALIDITY_DAYS = 14

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(verbose_name="e-mail")
    first_name = models.CharField(verbose_name="prénom", max_length=255)
    last_name = models.CharField(verbose_name="nom", max_length=255)
    sent = models.BooleanField(verbose_name="envoyée", default=False)
    validity_days = models.PositiveSmallIntegerField(
        verbose_name="durée de validité en jours",
        default=DEFAULT_VALIDITY_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
    )

    accepted = models.BooleanField(verbose_name="acceptée", default=False)
    accepted_at = models.DateTimeField(verbose_name="date d'acceptation", blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(verbose_name="date d'envoi", blank=True, null=True, db_index=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        abstract = True

    @classmethod
    def get_model_from_string(cls, model_string):
        """
        Retrieve the model to use depending on a string.
        Usage:
        invitation_model = Invitation.get_model_from_string("employer")
        invitation_model.objects.count()
        """
        if model_string == KIND_EMPLOYER:
            return EmployerInvitation
        elif model_string == KIND_PRESCRIBER:
            return PrescriberWithOrgInvitation
        elif model_string == KIND_LABOR_INSPECTOR:
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
    def acceptance_url_for_existing_user(self):
        """
        URL usable by an existing user to accept the invitation.
        """
        raise NotImplementedError

    @property
    def expiration_date(self):
        return self.sent_at + relativedelta(days=self.validity_days)

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
    USER_KIND = UserKind.PRESCRIBER
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="parrain ou marraine",
        on_delete=models.CASCADE,
        related_name="prescriber_org_invitations",
    )
    organization = models.ForeignKey(
        "prescribers.PrescriberOrganization", on_delete=models.CASCADE, related_name="invitations"
    )

    class Meta:
        verbose_name = "invitation prescripteurs"
        verbose_name_plural = "invitations prescripteurs"

    @property
    def acceptance_link(self):
        return get_absolute_url(
            reverse(
                "invitations_views:new_user", kwargs={"invitation_type": KIND_PRESCRIBER, "invitation_id": self.pk}
            )
        )

    @property
    def acceptance_url_for_existing_user(self):
        return reverse("invitations_views:join_prescriber_organization", kwargs={"invitation_id": self.pk})

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


class EmployerInvitation(InvitationAbstract):
    USER_KIND = UserKind.EMPLOYER
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="parrain ou marraine",
        on_delete=models.CASCADE,
        related_name="siae_invitations",
    )
    siae = models.ForeignKey("companies.Company", on_delete=models.CASCADE, related_name="invitations")

    class Meta:
        verbose_name = "invitation employeur"
        verbose_name_plural = "invitations employeurs"

    @property
    def acceptance_link(self):
        return get_absolute_url(
            reverse("invitations_views:new_user", kwargs={"invitation_type": KIND_EMPLOYER, "invitation_id": self.pk})
        )

    @property
    def acceptance_url_for_existing_user(self):
        return reverse("invitations_views:join_siae", kwargs={"invitation_id": self.pk})

    def add_invited_user_to_company(self):
        user = User.objects.get(email=self.email)
        self.siae.members.add(user)
        user.save()
        # We must be able to invite a former member of this SIAE
        # however `members.add()` does not update membership status if it already exists
        if user not in self.siae.active_members:
            membership = user.companymembership_set.get(is_active=False, siae=self.siae)
            membership.is_active = True
            membership.save()

    def guest_can_join_siae(self, request):
        user = get_object_or_404(User, email=self.email)
        return user == request.user and user.is_employer

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
    USER_KIND = UserKind.LABOR_INSPECTOR
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="parrain ou marraine",
        on_delete=models.CASCADE,
        related_name="institution_invitations",
    )
    institution = models.ForeignKey(
        "institutions.Institution", on_delete=models.CASCADE, related_name="labor_inspectors_invitations"
    )

    class Meta:
        verbose_name = "invitation inspecteurs du travail"
        verbose_name_plural = "invitations inspecteurs du travail"

    @property
    def acceptance_link(self):
        return get_absolute_url(
            reverse(
                "invitations_views:new_user",
                kwargs={"invitation_type": KIND_LABOR_INSPECTOR, "invitation_id": self.pk},
            )
        )

    @property
    def acceptance_url_for_existing_user(self):
        return reverse("invitations_views:join_institution", kwargs={"invitation_id": self.pk})

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
