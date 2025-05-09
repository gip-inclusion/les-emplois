import os
import uuid

from django.db import models
from django.utils import timezone


class File(models.Model):
    # S3 fields
    # https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
    # The name for a key is a sequence of Unicode characters whose UTF-8
    # encoding is at most 1024 bytes long.
    key = models.CharField(primary_key=True, max_length=1024)
    last_modified = models.DateTimeField("dernière modification sur Cellar", default=timezone.now)
    deleted_at = models.DateTimeField(
        verbose_name="supprimé le", help_text="Marqué pour suppression du stockage", null=True
    )

    class Meta:
        verbose_name = "fichier"

    @staticmethod
    def anonymized_filename(filename):
        """Really simple method to just change the file name.
        Don't check extension validity as it's already done in the form.
        See itou.files.forms.ContentTypeValidator
        """
        obfuscated_name = f"{uuid.uuid4()}"
        _, extension = os.path.splitext(filename)
        return f"{obfuscated_name}{extension}"
