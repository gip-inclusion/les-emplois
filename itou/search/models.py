from django.conf import settings
from django.db import models
from django.urls import reverse


class SavedSearch(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.CASCADE)
    name = models.CharField(max_length=50, verbose_name="nom de la recherche")
    query_params = models.CharField(verbose_name="paramètres de la recherche")
    created_at = models.DateTimeField(verbose_name="date de création", auto_now=True)

    class Meta:
        verbose_name = "recherche sauvegardée"
        verbose_name_plural = "recherches sauvegardées"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="search_name_unique")]

    def __str__(self):
        return self.name

    @property
    def url(self):
        return f"{reverse('search:employers_results')}?{self.query_params}"
