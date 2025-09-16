from django.conf import settings
from django.db import models
from django.urls import reverse


MAX_SAVED_SEARCHES_COUNT = 20


class SavedSearch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur", related_name="saved_searches", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=50, verbose_name="nom de la recherche")
    query_params = models.CharField(verbose_name="paramètres de la recherche")
    created_at = models.DateTimeField(verbose_name="date de création", auto_now=True)

    class Meta:
        verbose_name = "recherche enregistrée"
        verbose_name_plural = "recherches enregistrées"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_%(class)s_name_per_user",
                violation_error_message="Une recherche existe déjà avec ce nom.",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def url(self):
        return f"{reverse('search:employers_results')}?{self.query_params}"
