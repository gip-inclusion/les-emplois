import datetime
import functools
import operator

from django.utils import timezone

from itou.antivirus.models import Scan
from itou.files.models import File
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def get_relations(self):
        relations = {
            (remote_field.field.model, remote_field.field.name)
            for remote_field in File._meta.get_fields(include_hidden=True)
            if remote_field.is_relation
        }
        relations.remove((Scan, "file"))
        return relations

    def handle(self, *args, **options):
        linked_files_pks = functools.reduce(
            operator.or_,
            [
                set(model.objects.exclude(**{field: None}).values_list(field, flat=True))
                for model, field in self.get_relations()
            ],
        )
        _deletions, deletions_per_type = (
            File.objects.filter(last_modified__lte=timezone.now() - datetime.timedelta(days=1))
            .exclude(pk__in=linked_files_pks)
            .delete()
        )
        self.logger.info(f"Marked {deletions_per_type.get('files.File')} orphans files for deletion")
