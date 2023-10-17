from collections import defaultdict

from django.core.management.commands.loaddata import Command as LoadDataCommand


class Command(LoadDataCommand):
    BATCH_SIZE = 10_000

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
        # Don't store too much objects in memory to prevent OOM kills
        if len(self.to_create[model]) >= self.BATCH_SIZE:
            model.objects.bulk_create(self.to_create[model])
            self.to_create[model] = []
        return True
