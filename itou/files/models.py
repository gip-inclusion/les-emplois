import pathlib
import uuid

from django.core.files.storage import default_storage, storages
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

    class Meta:
        verbose_name = "fichier"

    def copy(self):
        """Return a new File with a copy of the file on the storage"""

        new_key = str(pathlib.Path(self.key).with_stem(str(uuid.uuid4())))
        with default_storage.open(self.key) as file:
            default_storage.save(new_key, file)
        return self.__class__.objects.create(key=new_key)

    def url(self, *args, **kwargs):
        return default_storage.url(self.key, *args, **kwargs)

    def public_url(self, *args, **kwargs):
        return storages["public"].url(self.key, *args, **kwargs)
