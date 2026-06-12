from collections import defaultdict

from django.core.management.commands.loaddata import Command as LoadDataCommand


class Command(LoadDataCommand):
    BATCH_SIZE = 1_000

    def load_label(self, fixture_label):
        self.to_create = defaultdict(list)
        super().load_label(fixture_label)
        for model, objects in self.to_create.items():
            model.objects.bulk_create(objects)

    def save_obj(self, obj):
        django_obj = obj.object
        self.models.add(django_obj.__class__)
        model = django_obj._meta.model
        self.to_create[model].append(django_obj)
        model_to_check = {model}

        if any(obj.m2m_data.values()):
            for accessor_name, object_list in obj.m2m_data.items():
                field = getattr(django_obj, accessor_name)
                model = field.through
                model_to_check |= {model}

                for target_object in object_list:
                    self.to_create[model].append(
                        model(
                            **{
                                field.source_field_name: django_obj,
                                f"{field.target_field_name}_id": target_object,
                            },
                        )
                    )
        # Don't store too much objects in memory to prevent OOM kills
        for model in model_to_check:
            objects = self.to_create[model]
            if len(objects) >= self.BATCH_SIZE:
                model.objects.bulk_create(objects)
                self.to_create[model] = []
        return True
