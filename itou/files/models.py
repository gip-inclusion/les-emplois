import pathlib
import uuid

from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone


class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    # S3 fields
    # https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
    # The name for a key is a sequence of Unicode characters whose UTF-8
    # encoding is at most 1024 bytes long.
    key = models.CharField(max_length=1024, unique=True)

    last_modified = models.DateTimeField("dernière modification sur Cellar", default=timezone.now)
    deleted_at = models.DateTimeField(
        verbose_name="supprimé le", help_text="Marqué pour suppression du stockage", null=True
    )

    class Meta:
        verbose_name = "fichier"

    def copy(self):
        """Return a new File with a copy of the file on the storage"""
        new_file = self.__class__.objects.create(key=self.anonymized_filename(self.key))
        with default_storage.open(self.key) as file:
            default_storage.save(new_file.key, file)
        return new_file

    @staticmethod
    def anonymized_filename(filename):
        """Really simple method to just change the file name.
        Don't check extension validity as it's already done in the form.
        See itou.files.forms.ContentTypeValidator
        """
        return str(pathlib.Path(filename).with_stem(str(uuid.uuid4())))
