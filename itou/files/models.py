import pathlib
import uuid

from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone


class FileManager(models.Manager):
    def create(self, key_prefix="", filename="", **obj_data):
        if obj_data.get("key") and (key_prefix or filename):
            raise KeyError("Inconsistent arguments. Please choose between a key or a couple key_prefix/filename.")
        if obj_data.get("key"):
            pathlike_key = pathlib.Path(obj_data["key"])
            try:
                # We should never have more than one level for the moment.
                [key_prefix, filename] = pathlike_key.parts
            except ValueError:
                raise ValueError("File tree depth is too deep. Only one level is allowed.", pathlike_key)
        if not key_prefix.endswith("/"):
            key_prefix = f"{key_prefix}/"
        obj_data["key"] = f"{key_prefix}{File.anonymized_filename(filename)}"
        return super().create(**obj_data)


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
    objects = FileManager()

    class Meta:
        verbose_name = "fichier"

    def copy(self):
        """Return a new File with a copy of the file on the storage"""
        new_file = self.__class__.objects.create(key=self.key)
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
