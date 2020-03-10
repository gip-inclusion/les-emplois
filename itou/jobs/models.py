import re
import string

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _


class Rome(models.Model):
    """
    A ROME.
    Data is provided by django-admin commands `generate_romes` and `import_romes`.
    """

    RIASEC_REALISTIC = "R"
    RIASEC_INVESTIGATIVE = "I"
    RIASEC_ARTISTIC = "A"
    RIASEC_SOCIAL = "S"
    RIASEC_ENTERPRISING = "E"
    RIASEC_CONVENTIONAL = "C"

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
    riasec_major = models.CharField(
        verbose_name=_("RIASEC Majeur"), max_length=1, choices=RIASEC_CHOICES, default=RIASEC_REALISTIC
    )
    riasec_minor = models.CharField(
        verbose_name=_("RIASEC Mineur"), max_length=1, choices=RIASEC_CHOICES, default=RIASEC_REALISTIC
    )
    code_isco = models.CharField(verbose_name=_("Code ROME"), max_length=4)

    class Meta:
        verbose_name = _("ROME")
        verbose_name_plural = _("ROMEs")

    def __str__(self):
        return f"{self.name} ({self.code})"


class AppellationQuerySet(models.QuerySet):
    def autocomplete(self, search_string, codes_to_exclude=None, limit=10):
        """
        A `search_string` equals to `foo bar` will match all results beginning with `foo` and `bar`.
        This is achieved via `to_tsquery` and prefix matching:
        https://www.postgresql.org/docs/11/textsearch-controls.html#TEXTSEARCH-PARSING-QUERIES
        """
        # Keep only words since `to_tsquery` only takes tokens as input.
        words = re.sub(f"[{string.punctuation}]", " ", search_string).split()
        words = [word + ":*" for word in words]
        tsquery = " & ".join(words)
        queryset = self.extra(where=["full_text @@ to_tsquery('french_unaccent', %s)"], params=[tsquery])
        queryset = queryset.select_related("rome")
        if codes_to_exclude:
            queryset = queryset.exclude(code__in=codes_to_exclude)
        return queryset[:limit]


class Appellation(models.Model):
    """
    A ROME's appellation.
    Data is provided by django-admin commands `generate_appellations_for_romes` and `import_appellations_for_romes`.

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
    rome = models.ForeignKey(Rome, on_delete=models.CASCADE, null=True, related_name="appellations")
    # A PostgreSQL trigger (defined in migrations) updates this field automatically.
    full_text = SearchVectorField(null=True)

    objects = models.Manager.from_queryset(AppellationQuerySet)()

    class Meta:
        verbose_name = _("Appellation")
        verbose_name_plural = _("Appellations")
        ordering = ["name"]
        indexes = [GinIndex(fields=["full_text"])]

    def __str__(self):
        return self.name
