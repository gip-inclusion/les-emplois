from collections import defaultdict

from django.core.management.commands.loaddata import Command as LoadDataCommand


class Command(LoadDataCommand):
    def load_label(self, fixture_label):
        self.to_create = defaultdict(list)
        super().load_label(fixture_label)
        for model, objects in self.to_create.items():
            model.objects.bulk_create(objects)

    def save_obj(self, obj):
        django_obj = obj.object
        self.models.add(django_obj.__class__)
        self.to_create[django_obj._meta.model].append(django_obj)
        return True
