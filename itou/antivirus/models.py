from django.db import models
from django.utils.text import capfirst

from itou.files.models import File


class Scan(models.Model):
    file = models.OneToOneField(File, on_delete=models.CASCADE)
    clamav_signature = models.TextField()
    clamav_completed_at = models.DateTimeField(null=True, db_index=True, verbose_name="analyse ClamAV le")
    infected = models.BooleanField(null=True, verbose_name="fichier infecté")
    comment = models.TextField(blank=True, verbose_name="commentaire")

    class Meta:
        verbose_name = "analyse antivirus"
        verbose_name_plural = "analyses antivirus"

    def __str__(self):
        text = f"{capfirst(self._meta.verbose_name)} {self.file_id}"
        if self.infected:
            text = f"[VIRUS] {text}"
        return text
