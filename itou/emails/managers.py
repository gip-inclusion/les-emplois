from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class EmailAddressManager(models.Manager):
    def get_new(self, user):
        """
        Returns the email address the user is in the process of changing to, if any.
        """
        return self.model.objects.filter(user=user, verified=False).last()

    def add_new_email(self, user, email, send_confirmation=True, signup=False):
        """
        Adds email address to user, non-verified and optionally sends a confirmation email.
        If an existing non-verified email exists for the user, it will be replaced.
        """
        instance = self.get_new(user)
        email = email.lower()

        if not instance:
            instance = self.model.objects.create(user=user, email=email)
        else:
            # User can only request one email modification at a time.
            instance.email = email
            instance.verified = False
            instance.save()

        # Send confirmation email
        if send_confirmation:
            instance.send_confirmation(signup=signup)

        return instance

    def get_verified(self, user):
        return self.filter(user=user, verified=True).order_by("pk").first()

    def get_primary(self, user):
        try:
            return self.get(user=user, primary=True)
        except self.model.DoesNotExist:
            return None

    def get_primary_email(self, user) -> str | None:
        from allauth.account.utils import user_email

        primary = self.get_primary(user)
        if primary:
            email = primary.email
        else:
            email = user_email(user)
        return email

    def is_verified(self, email):
        return self.filter(email=email.lower(), verified=True).exists()

    def lookup(self, emails):
        return self.filter(email__in=[e.lower() for e in emails])


class EmailConfirmationManager(models.Manager):
    def all_expired(self):
        return self.filter(self.expired_q())

    def all_valid(self):
        return self.exclude(self.expired_q()).filter(email_address__verified=False)

    def expired_q(self):
        sent_threshold = timezone.now() - timedelta(days=settings.EMAIL_CONFIRMATION_EXPIRE_DAYS)
        return Q(sent__lt=sent_threshold)

    def delete_expired_confirmations(self):
        self.all_expired().delete()
