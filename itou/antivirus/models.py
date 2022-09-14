from django.db import models
from django.utils import timezone
from django.utils.text import capfirst


class FileScanReport(models.Model):
    # https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
    # The name for a key is a sequence of Unicode characters whose UTF-8
    # encoding is at most 1024 bytes long.
    key = models.CharField(primary_key=True, max_length=1024)
    # https://docs.clamav.net/manual/Signatures/SignatureNames.html
    signature = models.CharField(max_length=255)
    reported_at = models.DateTimeField(default=timezone.now)
    virus = models.BooleanField(null=True, verbose_name="fichier infecté")
    comment = models.TextField(blank=True, verbose_name="commentaire")

    class Meta:
        verbose_name = "rapport d’analyse"
        verbose_name_plural = "rapports d’analyse"

    def __str__(self):
        return f"{capfirst(self._meta.verbose_name)} pour {self.key}"
