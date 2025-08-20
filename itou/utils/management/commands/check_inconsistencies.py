from django.apps import apps
from django.conf import settings
from django.contrib.admin import site
from django.contrib.admin.exceptions import NotRegistered
from django.urls import reverse

from itou.utils.command import BaseCommand
from itou.utils.slack import send_slack_message
from itou.utils.templatetags.str_filters import pluralizefr
from itou.utils.urls import get_absolute_url


def get_admin_absolute_url(obj):
    return get_absolute_url(reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk]))


class Command(BaseCommand):
    def handle(self, verbosity, **options):
        inconsistencies = {}
        for app in apps.get_app_configs():
            for model in app.get_models():
                try:
                    model_admin = site.get_model_admin(model)
                except NotRegistered:
                    continue
                if getattr(model_admin, "INCONSISTENCY_CHECKS", None):
                    model_inconsistencies = model_admin.compute_inconsistencies(model.objects.all())
                    self.logger.info(
                        "Model: %s - found %s inconsistencies", model.__name__, len(model_inconsistencies)
                    )
                    inconsistencies.update(model_inconsistencies)
        s = pluralizefr(len(inconsistencies))
        msg_lines = [f"{len(inconsistencies)} incohérence{s} trouvée{s}:"]
        for obj, errors in inconsistencies.items():
            obj_url = get_admin_absolute_url(obj)
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
