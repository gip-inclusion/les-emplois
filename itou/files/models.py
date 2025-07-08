import pathlib
import uuid

from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone


def save_file(folder, file, storage="", anonymize_filename=True):
    if not storage:
        storage = default_storage
    if len(pathlib.Path(folder).parts) > 1:
        raise NotImplementedError("File tree depth is too deep. Only one level is allowed.", folder)
    # Only keep the final part to avoid subfolders.
    filename = pathlib.Path(file.name).name
    if anonymize_filename:
        filename = File.anonymized_filename(filename)
    key = pathlib.Path(folder) / filename
    key = storage.save(key, file)
    file = File.objects.create(key=key)
    return file


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

    @staticmethod
    def anonymized_filename(filename):
        """Really simple method to just change the file name.
        Don't check extension validity as it's already done in the form.
        See itou.files.forms.ContentTypeValidator
        """
        pathlike_filename = pathlib.Path(filename)
        return f"{uuid.uuid4()}{pathlike_filename.suffix}"
