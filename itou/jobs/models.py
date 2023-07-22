import re
import string

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


# This list has been retrieved by an API call to
# <PE_API_URL>/partenaire/rome/v1/granddomaine
ROME_DOMAINS = {
    "A": "Agriculture et Pêche, Espaces naturels et Espaces verts, Soins aux animaux",
    "B": "Arts et Façonnage d'ouvrages d'art",
    "C": "Banque, Assurance, Immobilier",
    "D": "Commerce, Vente et Grande distribution",
    "E": "Communication, Média et Multimédia",
    "F": "Construction, Bâtiment et Travaux publics",
    "G": "Hôtellerie-Restauration, Tourisme, Loisirs et Animation",
    "H": "Industrie",
    "I": "Installation et Maintenance",
    "J": "Santé",
    "K": "Services à la personne et à la collectivité",
    "L": "Spectacle",
    "M": "Support à l'entreprise",
    "N": "Transport et Logistique",
}


class Rome(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    code = models.CharField(verbose_name="code ROME", max_length=5, primary_key=True)
    name = models.CharField(verbose_name="nom", max_length=255, db_index=True)

    class Meta:
        verbose_name = "ROME"
        verbose_name_plural = "ROME"

    def __str__(self):
        return f"{self.name} ({self.code})"


class AppellationQuerySet(models.QuerySet):
    def autocomplete(self, search_string, codes_to_exclude=None, limit=10, rome_code=None):
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
        if rome_code:
            queryset = queryset.filter(rome__code=rome_code)
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

    updated_at = models.DateTimeField(auto_now=True)
    code = models.CharField(verbose_name="code", max_length=6, primary_key=True)
    name = models.CharField(verbose_name="nom", max_length=255, db_index=True)
    rome = models.ForeignKey(Rome, on_delete=models.CASCADE, null=True, related_name="appellations")
    # A PostgreSQL trigger (defined in migrations) updates this field automatically.
    full_text = SearchVectorField(null=True)

    objects = AppellationQuerySet.as_manager()

    class Meta:
        verbose_name = "appellation"
        ordering = ["name"]
        indexes = [GinIndex(fields=["full_text"])]

    def __str__(self):
        return self.name
