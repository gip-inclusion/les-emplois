from django.apps import apps
from django.conf import settings
from django.contrib.admin import site
from django.contrib.admin.exceptions import NotRegistered
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch

from itou.utils.command import BaseCommand
from itou.utils.slack import send_slack_message
from itou.utils.templatetags.str_filters import pluralizefr
from itou.utils.urls import get_absolute_url


def get_admin_absolute_url(obj):
    try:
        return get_absolute_url(reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk]))
    except NoReverseMatch:
        return None


def get_fields_with_dict_limit_choices(model):
    fields = []
    for field in model._meta.get_fields():
        if not hasattr(field, "get_limit_choices_to"):
            continue

        limit_choices_to = field.get_limit_choices_to()
        if limit_choices_to and isinstance(limit_choices_to, dict):
            fields.append(field)
    return fields


def check_limit_choices_to_inconsistencies(queryset):
    inconsistencies = {}
    for field in get_fields_with_dict_limit_choices(queryset.model):
        limit_choices_to = field.get_limit_choices_to()
        joined_limit_choices_to = {f"{field.name}__{key}": value for key, value in limit_choices_to.items()}
        title = f"La valeur du champ '{field.name}' ({field.verbose_name}) ne respecte pas {limit_choices_to}"
        for item in queryset.filter(**{f"{field.name}__isnull": False}).exclude(**joined_limit_choices_to):
            inconsistencies.setdefault(item, []).append(title)
    return inconsistencies


class Command(BaseCommand):
    def handle(self, verbosity, **options):
        inconsistencies = {}
        for app in apps.get_app_configs():
            for model in app.get_models():
                # Check limit_choices_to (at least in dict fornat) for all models
                if get_fields_with_dict_limit_choices(model):
                    limit_choices_inconsistencies = check_limit_choices_to_inconsistencies(model.objects.all())
                    self.logger.info(
                        "Model: %s - found %s limit_choices_to inconsistencies",
                        model.__name__,
                        len(limit_choices_inconsistencies),
                    )
                    for item, errors in limit_choices_inconsistencies.items():
                        inconsistencies.setdefault(item, []).extend(errors)

                # Check INCONSISTENCY_CHECKS for models that have it registered in their ModelAdmin
                try:
                    model_admin = site.get_model_admin(model)
                except NotRegistered:
                    continue
                if getattr(model_admin, "compute_inconsistencies", None):
                    model_inconsistencies = model_admin.compute_inconsistencies(model.objects.all())
                    self.logger.info(
                        "Model: %s - found %s inconsistencies", model.__name__, len(model_inconsistencies)
                    )
                    inconsistencies.update(model_inconsistencies)
        s = pluralizefr(len(inconsistencies))
        msg_lines = [f"{len(inconsistencies)} incohérence{s} trouvée{s}:"]
        for obj, errors in inconsistencies.items():
            obj_url = get_admin_absolute_url(obj) or obj
            msg_lines.append(f" - {obj_url} : {errors}")
        if not inconsistencies:
            msg_lines.append("Bon boulot :not-bad:")

        inconsistencies_msg = "\n".join(msg_lines)

        if settings.SLACK_INCONSISTENCIES_WEBHOOK_URL:
            send_slack_message(
                text=inconsistencies_msg,
                url=settings.SLACK_INCONSISTENCIES_WEBHOOK_URL,
            )
        else:
            self.logger.error("Found %s inconsistencies but no slack webhook configured", len(inconsistencies))
        if verbosity > 1:
            print(inconsistencies_msg)
