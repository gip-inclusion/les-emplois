from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Rome(models.Model):
    """
    A ROME.
    Data provided by `django-admin import_romes`.
    """

    RIASEC_REALISTIC = 'R'
    RIASEC_INVESTIGATIVE = 'I'
    RIASEC_ARTISTIC = 'A'
    RIASEC_SOCIAL = 'S'
    RIASEC_ENTERPRISING = 'E'
    RIASEC_CONVENTIONAL = 'C'

    RIASEC_CHOICES = (
        (RIASEC_REALISTIC, _("Réaliste")),
        (RIASEC_INVESTIGATIVE, _("Investigateur")),
        (RIASEC_ARTISTIC, _("Artistique")),
        (RIASEC_SOCIAL, _("Social")),
        (RIASEC_ENTERPRISING, _("Entreprenant")),
        (RIASEC_CONVENTIONAL, _("Conventionnel")),
    )

    code = models.CharField(verbose_name=_("Code ROME"), max_length=5, primary_key=True)
    name = models.CharField(verbose_name=_("Nom"), max_length=255, db_index=True)
    riasec_major = models.CharField(verbose_name=_("RIASEC Majeur"), max_length=1, choices=RIASEC_CHOICES,
        default=RIASEC_REALISTIC)
    riasec_minor = models.CharField(verbose_name=_("RIASEC Mineur"), max_length=1, choices=RIASEC_CHOICES,
        default=RIASEC_REALISTIC)
    code_isco = models.CharField(verbose_name=_("Code ROME"), max_length=4)

    class Meta:
        verbose_name = _("ROME")
        verbose_name_plural = _("ROMEs")

    def __str__(self):
        return f"{self.name} ({self.code})"


class AppellationQuerySet(models.QuerySet):

    def autocomplete(self, term, codes_to_exclude=None, limit=10):

        terms = term.split()

        q_query = Q()
        for term in terms:
            q_query &= Q(short_name__icontains=term) | Q(rome__code__icontains=term)

        queryset = self.filter(q_query).select_related('rome')

        if codes_to_exclude:
            queryset = queryset.exclude(code__in=codes_to_exclude)

        return queryset[:limit]


class Appellation(models.Model):
    """
    A ROME's appellation.
    Data provided by `django-admin import_appellations_for_romes`.

    A job is characterized by a ROME code and a name, but it can have many different appellations.

    For example, the job M1805 - "Études et développement informatique" can be called:

    - "Analyste d'étude informatique"
    - "Analyste en cybersécurité"
    - "Analyste réseau informatique"
    - "Développeur / Développeuse full-stack"
    - "Développeur / Développeuse - jeux vidéo"
    - "Développeur / Développeuse web"
    - "Ingénieur / Ingénieure analyste en système d'information"
    - "Paramétreur / Paramétreuse logiciel ERP"
    - etc.
    """

    code = models.CharField(verbose_name=_("Code"), max_length=6, primary_key=True)
    name = models.CharField(verbose_name=_("Nom"), max_length=255, db_index=True)
    short_name = models.CharField(verbose_name=_("Nom court"), max_length=255, db_index=True)
    rome = models.ForeignKey(Rome, on_delete=models.CASCADE, null=True, related_name="appellations")

    objects = models.Manager.from_queryset(AppellationQuerySet)()

    class Meta:
        verbose_name = _("Appellation")
        verbose_name_plural = _("Appellations")
        ordering = ['short_name', 'name']

    def __str__(self):
        return self.name
