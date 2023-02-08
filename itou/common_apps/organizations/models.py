import uuid

from django.conf import settings
from django.db import models
from django.db.models import Prefetch, Q
from django.utils import timezone

from itou.utils.emails import get_email_message


class OrganizationQuerySet(models.QuerySet):
    """
    Common methods used by Siae, PrescriberOrganization and Institution models query sets.
    """

    def member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(members=user, members__is_active=True)

    def prefetch_active_memberships(self):
        membership_model = self.model.members.through
        membership_set_related_name = membership_model.user.field.remote_field.get_accessor_name()
        qs = membership_model.objects.active().select_related("user").order_by("-is_admin", "joined_at")
        return self.prefetch_related(Prefetch(membership_set_related_name, queryset=qs))


class OrganizationAbstract(models.Model):
    """
    Base model for Siae, Prescriber Organization and Institution models.
    """

    name = models.CharField(verbose_name="Nom", max_length=255)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True)

    # This unique ID is supposed to used as a globally unique reference and should never be changed,
    # if the organization is supposed to be the same (even in the case of a change of address or SIRET)
    # It is meant to be the exposed ID of our organizations for external clients, such as in our APIs.
    # This enables us to keep our internal primary key opaque and independent from any external logic.
    uid = models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)

    # Child class should have a "members" attribute, for example:
    # members = models.ManyToManyField(
    #     settings.AUTH_USER_MODEL,
    #     verbose_name="Membres",
    #     through="PrescriberMembership",
    #     blank=True,
    #     through_fields=("organization", "user"),
    # )
    objects = OrganizationQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name}"

    def get_admins(self):
        memberships = self.memberships.admin()
        return MembershipQuerySet.to_users_qs(memberships=memberships)

    def has_member(self, user):
        return self.active_members.filter(pk=user.pk).exists()

    def has_admin(self, user):
        return self.active_admin_members.filter(pk=user.pk).exists()

    def add_member(self, user):
        is_admin = self.members.count() == 0
        membership = self.memberships.create(user=user, is_admin=is_admin)
        membership.save()

    @property
    def active_members(self):
        memberships = self.memberships.active()
        return MembershipQuerySet.to_users_qs(memberships=memberships)

    @property
    def active_admin_members(self):
        memberships = self.memberships.active_admin()
        return MembershipQuerySet.to_users_qs(memberships=memberships)

    @property
    def deactivated_members(self):
        """
        List of organization removed members but still active as users.
        """
        memberships = self.memberships.inactive()
        return MembershipQuerySet.to_users_qs(memberships=memberships)

    @property
    def display_name(self):
        return self.name.capitalize()

    @property
    def has_members(self):
        return self.active_members.exists()

    @property
    def memberships(self):
        """
        Get memberships linked to this organization.
        In short, self.memberships.get(user=user.pk)
        is the same as siae.siaemembership_set.get(user=user.pk).
        ---
        At this level, we don't know the organization model as it is defined later in the child class.
        Using self.members.though is a trap as it returns the model Manager and not a query set!
        `self.members.through.objects.get(user=user.pk)` returns every membership for that user
        but NOT for a couple user / organization.
        """
        membership_model = self.members.through
        membership_set_related_name = membership_model.user.field.remote_field.get_accessor_name()
        return getattr(self, membership_set_related_name)

    #### Emails ####
    def add_admin_email(self, user):
        """
        Tell a member he is an administrator now.
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/add_admin_email_subject.txt"
        body = "common/emails/add_admin_email_body.txt"
        return get_email_message(to, context, subject, body)

    def remove_admin_email(self, user):
        """
        Tell a member he is no longer an administrator.
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/remove_admin_email_subject.txt"
        body = "common/emails/remove_admin_email_body.txt"
        return get_email_message(to, context, subject, body)

    def member_deactivation_email(self, user):
        """
        Tell a user he is no longer a member of this organization.
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/member_deactivation_email_subject.txt"
        body = "common/emails/member_deactivation_email_body.txt"
        return get_email_message(to, context, subject, body)


class MembershipQuerySet(models.QuerySet):
    @property
    def active_lookup(self):
        return Q(is_active=True)

    @property
    def admin_lookup(self):
        # Active or inactive admins
        return Q(is_admin=True, user__is_active=True)

    def active(self):
        """
        * user.is_active: user is able to do something on the platform.
        * user.membership.is_active: is a member of this structure.
        """
        return self.filter(user__is_active=True).filter(self.active_lookup)

    def inactive(self):
        return self.filter(user__is_active=True).exclude(self.active_lookup)

    def admin(self):
        return self.filter(self.admin_lookup)

    def active_admin(self):
        return self.active().filter(self.admin_lookup)

    @staticmethod
    def to_users_qs(memberships):
        """
        Return a User QuerySet. Useful to iterate over User objects instead of Membership ones.
        """
        user_field = memberships.model._meta.get_field("user")
        remote_field_lookup = user_field.remote_field.name  # for exemple "siaememberships"
        return user_field.related_model.objects.filter(**{f"{remote_field_lookup}__in": memberships})


class MembershipAbstract(models.Model):
    """
    Abstract class to handle memberships.
    Inherit from it to create an intermediary model between `User` and another model.
    Example: itou.prescribers.models.PrescriberMembership

    The child model should implement the following elements:
    ```
    related_model = models.ForeignKey(MyModel, on_delete=models.CASCADE)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_membershipmodel_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Mis à jour par",
    )

    class Meta:
        unique_together = ("user_id", "related_model_id")
    ```
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name="Date d'adhésion", default=timezone.now)
    is_admin = models.BooleanField(verbose_name="Administrateur", default=False)
    is_active = models.BooleanField("Rattachement actif", default=True)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", null=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def deactivate_membership_by_user(self, updated_by):
        """
        Deleting the membership was a possibility but we would have lost
        the member activity history. We need it to show to other members
        which job applications this user was managing before leaving the organization.
        """
        self.is_active = False
        # If this member is invited again, he should no still be an administrator.
        # Remove admin rights as a precaution.
        self.is_admin = False
        self.updated_by = updated_by
        return True

    def set_admin_role(self, is_admin, updated_by):
        self.is_admin = is_admin
        self.updated_by = updated_by
