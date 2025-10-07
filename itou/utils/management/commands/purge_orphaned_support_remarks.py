from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef

from itou.utils.command import BaseCommand, dry_runnable
from itou.utils.models import PkSupportRemark, UUIDSupportRemark


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, **options):
        model_to_content_type_ids = {}
        for model in [PkSupportRemark, UUIDSupportRemark]:
            model_to_content_type_ids[model] = list(model.objects.values_list("content_type", flat=True).distinct())

        existing_content_types = {}
        for content_type in ContentType.objects.filter(pk__in=set().union(*model_to_content_type_ids.values())):
            if content_type.model_class() is None:
                self.logger.error(
                    (
                        "SupportRemark objects linked to non existing model %s.%s. "
                        "Please run remove_stale_contenttypes --include-stale-apps command for cleanup."
                    ),
                    content_type.app_label,
                    content_type.model,
                )
                continue
            existing_content_types[content_type.pk] = content_type

        for remark_model, content_type_ids in model_to_content_type_ids.items():
            for content_type_id in content_type_ids:
                content_type = existing_content_types.get(content_type_id)
                if content_type is None:
                    # They will be deleted by remove_stale_contenttypes command
                    continue
                self.purge_remarks_for_model(remark_model, content_type)

    def purge_remarks_for_model(self, remark_model, content_type):
        linked_model = content_type.model_class()
        _, objs = (
            remark_model.objects.filter(content_type_id=content_type)
            .exclude(Exists(linked_model.objects.filter(pk=OuterRef("object_id"))))
            .delete()
        )
        deleted_remarks_nb = objs.get(remark_model._meta.label, 0)
        self.logger.info(
            "Deleted count=%d obsolete %s remarks linked to %s",
            deleted_remarks_nb,
            remark_model.__name__,
            linked_model._meta.label,
        )
