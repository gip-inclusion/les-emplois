import datetime

from allauth.account import signals
from allauth.account.adapter import get_adapter
from citext import CIEmailField
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core import signing
from django.db import models
from django.utils import timezone

from itou.emails.managers import EmailAddressManager, EmailConfirmationManager


class Email(models.Model):
    to = ArrayField(CIEmailField(), blank=True, verbose_name="à")
    cc = ArrayField(CIEmailField(), blank=True, default=list, verbose_name="cc")
    bcc = ArrayField(CIEmailField(), blank=True, default=list, verbose_name="cci")
    subject = models.TextField(verbose_name="sujet", blank=True)
    body_text = models.TextField(verbose_name="message", blank=True)
    from_email = CIEmailField(verbose_name="de")
    reply_to = ArrayField(CIEmailField(), blank=True, default=list, verbose_name="répondre à")
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="demande d’envoi à")
    esp_response = models.JSONField(null=True, verbose_name="réponse du fournisseur d’e-mail")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            GinIndex(name="recipients_idx", fields=["to", "cc", "bcc"]),
        ]

    def __str__(self):
        return f"email {self.pk}: {self.subject}"

    @staticmethod
    def from_email_message(email_message):
        return Email(
            from_email=email_message.from_email,
            reply_to=email_message.reply_to,
            to=email_message.to,
            cc=email_message.cc,
            bcc=email_message.bcc,
            subject=email_message.subject,
            body_text=email_message.body,
        )


class EmailAddress(models.Model):
    """
    An email address associated to a user. A user will have only one primary email address (User.email),
    but they may have a second email address in the process of validation.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.CASCADE, related_name="email_addresses"
    )
    email = models.EmailField(
        db_index=True,
        max_length=settings.EMAIL_ADDRESS_MAX_LENGTH,
        verbose_name="adresse e-mail",
    )
    verified = models.BooleanField(verbose_name="vérifiée", default=False)

    objects = EmailAddressManager()

    class Meta:
        verbose_name = "adresse e-mail"
        verbose_name_plural = "adresses e-mail"

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = self.email.lower()

    def can_set_verified(self):
        if self.verified:
            return True
        return not EmailAddress.objects.exclude(pk=self.pk).filter(verified=True, email=self.email).exists()

    def set_verified(self, commit=True):
        if self.verified:
            return True
        if self.can_set_verified():
            self.verified = True
            if commit:
                self.save(update_fields=["verified"])
        return self.verified

    def send_confirmation(self, request=None, signup=False):
        confirmation = EmailConfirmationHMAC.create(self)
        confirmation.send(request, signup=signup)
        return confirmation

    def remove(self):
        from allauth.account.utils import user_email

        self.delete()
        if user_email(self.user) == self.email:
            alt = EmailAddress.objects.filter(user=self.user).order_by("-verified").first()
            alt_email = ""
            if alt:
                alt_email = alt.email
            user_email(self.user, alt_email, commit=True)


class EmailConfirmationMixin:
    def confirm(self, request):
        email_address = self.email_address
        if not email_address.verified:
            confirmed = get_adapter().confirm_email(request, email_address)
            if confirmed:
                return email_address

    def send(self, request=None, signup=False):
        get_adapter().send_confirmation_mail(request, self, signup)
        signals.email_confirmation_sent.send(
            sender=self.__class__,
            request=request,
            confirmation=self,
            signup=signup,
        )


class EmailConfirmation(EmailConfirmationMixin, models.Model):
    email_address = models.ForeignKey(
        EmailAddress,
        verbose_name="adresse e-mail",
        on_delete=models.CASCADE,
    )
    created = models.DateTimeField(verbose_name="créé", default=timezone.now)
    sent = models.DateTimeField(verbose_name="envoyé", null=True)
    key = models.CharField(verbose_name="clé", max_length=64, unique=True)

    objects = EmailConfirmationManager()

    class Meta:
        verbose_name = "confirmation par e-mail"
        verbose_name_plural = "confirmations par e-mail"

    def __str__(self):
        return f"confirmation for {self.email_address}"

    @classmethod
    def create(cls, email_address):
        key = get_adapter().generate_emailconfirmation_key(email_address.email)
        return cls._default_manager.create(email_address=email_address, key=key)

    @classmethod
    def from_key(cls, key):
        qs = EmailConfirmation.objects.all_valid()
        qs = qs.select_related("email_address__user")
        emailconfirmation = qs.filter(key=key.lower()).first()
        return emailconfirmation

    def key_expired(self):
        expiration_date = self.sent + datetime.timedelta(days=settings.EMAIL_CONFIRMATION_EXPIRE_DAYS)
        return expiration_date <= timezone.now()

    key_expired.boolean = True  # type: ignore[attr-defined]

    def confirm(self, request):
        if not self.key_expired():
            return super().confirm(request)

    def send(self, request=None, signup=False):
        super().send(request=request, signup=signup)
        self.sent = timezone.now()
        self.save()


class EmailConfirmationHMAC(EmailConfirmationMixin):
    def __init__(self, email_address):
        self.email_address = email_address

    @classmethod
    def create(cls, email_address):
        return EmailConfirmationHMAC(email_address)

    @property
    def key(self):
        return signing.dumps(obj=self.email_address.pk, salt=settings.EMAIL_CONFIRMATION_SALT)

    @classmethod
    def from_key(cls, key):
        try:
            max_age = 60 * 60 * 24 * settings.EMAIL_CONFIRMATION_EXPIRE_DAYS
            pk = signing.loads(key, max_age=max_age, salt=settings.EMAIL_CONFIRMATION_SALT)
            ret = EmailConfirmationHMAC(EmailAddress.objects.get(pk=pk, verified=False))
        except (
            signing.SignatureExpired,
            signing.BadSignature,
            EmailAddress.DoesNotExist,
        ):
            ret = None
        return ret

    def key_expired(self):
        return False
