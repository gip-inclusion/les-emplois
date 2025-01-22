import datetime

from allauth.account import signals
from allauth.account.adapter import get_adapter
from citext import CIEmailField
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core import signing
from django.db import models
from django.urls import reverse
from django.utils import timezone

from itou.emails.managers import EmailAddressManager, EmailConfirmationManager
from itou.utils.urls import get_absolute_url


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
    primary = models.BooleanField(verbose_name="principale", default=False)
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

    def set_as_primary(self, conditional=False):
        """Marks the email address as primary. In case of `conditional`, it is
        only marked as primary if there is no other primary email address set.
        """
        from allauth.account.utils import user_email

        old_primary = EmailAddress.objects.get_primary(self.user)
        if old_primary:
            if conditional:
                return False
            old_primary.primary = False
            old_primary.save()
        self.primary = True
        self.save()
        user_email(self.user, self.email, commit=True)
        return True

    def send_confirmation(self, request=None, signup=False):
        confirmation = EmailConfirmation.create(self)
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


class EmailConfirmation(models.Model):
    email_address = models.ForeignKey(
        EmailAddress,
        verbose_name="adresse e-mail",
        on_delete=models.CASCADE,
    )
    created = models.DateTimeField(verbose_name="créé", default=timezone.now)
    sent = models.DateTimeField(verbose_name="envoyé", null=True)
    key = models.CharField(verbose_name="clé", max_length=64, unique=True)
    used = models.BooleanField(
        verbose_name="utilisée",
        default=False,
        help_text="Pour des raisons de sécurité, un lien de confirmation ne peut être utilisé qu'une seule fois.",
    )

    objects = EmailConfirmationManager()

    class Meta:
        verbose_name = "confirmation par e-mail"
        verbose_name_plural = "confirmations par e-mail"

    def __str__(self):
        return f"confirmation for {self.email_address}"

    @classmethod
    def generate_key(cls, email_address):
        return signing.dumps(obj=email_address.pk, salt=settings.EMAIL_CONFIRMATION_SALT)

    @classmethod
    def create(cls, email_address):
        return cls._default_manager.create(email_address=email_address, key=cls.generate_key(email_address))

    @classmethod
    def from_key(cls, key):
        try:
            max_age = 60 * 60 * 24 * settings.EMAIL_CONFIRMATION_EXPIRE_DAYS
            pk = signing.loads(key, max_age=max_age, salt=settings.EMAIL_CONFIRMATION_SALT)
            email_address = EmailAddress.objects.get(pk=pk, verified=False)
            ret = EmailConfirmation.objects.filter(email_address=email_address, used=False).first()
        except (
            signing.SignatureExpired,
            signing.BadSignature,
            EmailAddress.DoesNotExist,
        ):
            ret = None
        return ret

    @property
    def get_key(self):
        return EmailConfirmation.generate_key(self.email_address.pk)

    def get_confirmation_url(self, absolute_url=False):
        url = reverse("accounts:account_confirm_email", args=[self.key])
        return get_absolute_url(url) if absolute_url else url

    def key_expired(self):
        expiration_date = self.sent + datetime.timedelta(days=settings.EMAIL_CONFIRMATION_EXPIRE_DAYS)
        return expiration_date <= timezone.now()

    def can_confirm_email(self):
        return not self.used and not self.email_address.verified and not self.key_expired()

    def confirm(self, request):
        if self.can_confirm_email():
            confirmed = get_adapter().confirm_email(request, self.email_address)
            if confirmed:
                return self.email_address

    def send(self, request=None, signup=False):
        get_adapter().send_confirmation_mail(request, self, signup)
        signals.email_confirmation_sent.send(
            sender=self.__class__,
            request=request,
            confirmation=self,
            signup=signup,
        )

        self.sent = timezone.now()
        self.save()
