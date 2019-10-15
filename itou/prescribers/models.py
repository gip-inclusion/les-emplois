from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.address.models import AddressMixin
from itou.utils.tokens import generate_random_token
from itou.utils.validators import validate_siret


class PrescriberOrganizationQuerySet(models.QuerySet):
    def member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(members=user, members__is_active=True)


class PrescriberOrganization(AddressMixin):  # Do not forget the mixin!
    """
    The organization of a prescriber, e.g.: Pôle emploi, missions locales, Cap emploi etc.

    Note: it is not required for a prescriber to be a member of an organization.
    """

    siret = models.CharField(
        verbose_name=_("Siret"), max_length=14, validators=[validate_siret], blank=True
    )
    name = models.CharField(verbose_name=_("Nom"), max_length=255, blank=True)
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=20, blank=True)
    email = models.EmailField(verbose_name=_("E-mail"), blank=True)
    website = models.URLField(verbose_name=_("Site web"), blank=True)
    description = models.TextField(verbose_name=_("Description"), blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Membres"),
        through="PrescriberMembership",
        blank=True,
    )
    secret_code = models.CharField(
        verbose_name=_("Code secret"),
        help_text=_("Code permettant à un utilisateur de rejoindre l'organisation."),
        max_length=6,
        default=generate_random_token,
        unique=True,
    )
    is_authorized = models.BooleanField(
        verbose_name=_("Habilitation"),
        default=False,
        help_text=_("Précise si l'organisation est habilitée par le préfet."),
    )

    objects = models.Manager.from_queryset(PrescriberOrganizationQuerySet)()

    class Meta:
        verbose_name = _("Organisation")
        verbose_name_plural = _("Organisations")

    def __str__(self):
        return f"{self.siret} {self.name}"

    @property
    def display_name(self):
        return self.name.title()

    @property
    def admins(self):
        return self.members.filter(prescribermembership__is_admin=True)


class PrescriberMembership(models.Model):
    """Intermediary model between `User` and `PrescriberOrganization`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ForeignKey(PrescriberOrganization, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(
        verbose_name=_("Date d'adhésion"), default=timezone.now
    )
    is_admin = models.BooleanField(
        verbose_name=_("Administrateur de la structure d'accompagnement"), default=False
    )
