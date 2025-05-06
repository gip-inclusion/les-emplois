import pathlib
import uuid

from django.core.files.storage import default_storage
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

    def copy(self):
        """Return a new File with a copy of the file on the storage"""

        new_key = str(pathlib.Path(self.key).with_stem(str(uuid.uuid4())))
        with default_storage.open(self.key) as file:
            default_storage.save(new_key, file)
        return self.__class__.objects.create(key=new_key)
