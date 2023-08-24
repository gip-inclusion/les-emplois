from django.apps import apps
from django.conf import settings
from django.core.checks import Error


VALID_UPPER_NAMES = frozenset(["CV", "DDETS", "GEIQ", "ID", "NIR", "NTT", "PASS", "QPV", "ROME", "SIAE", "URL", "ZRR"])


def bad_name(name):
    first_word, *rest = name.split()
    return first_word[0].isupper() and first_word not in VALID_UPPER_NAMES


def suggest_name(name):
    return name[0].lower() + name[1:]


def check_verbose_name_lower(app_configs, **kwargs):
    if app_configs is None:
        app_configs = [
            ac for ac in apps.app_configs.values() if ac.name in settings.INSTALLED_APPS if ac.name.startswith("itou.")
        ]
    models = (m for m in apps.get_models() if m._meta.app_config in app_configs)

    errors = []
    for model in models:
        for fieldname in ["verbose_name", "verbose_name_plural"]:
            try:
                name = getattr(model._meta, fieldname)
            except AttributeError:
                pass
            else:
                if bad_name(name):
                    errors.append(
                        Error(
                            f"Model {model} {fieldname} should be lower cased.",
                            hint=f"Rename {fieldname} from “{name}” to “{suggest_name(name)}”.",
                            obj=model,
                        )
                    )
        for field in model._meta.get_fields():
            exclude_predicates = [
                field.is_relation and field.auto_created,  # Reverse side of the relation
                field.is_relation and field.related_model is None,  # GenericForeignKey
            ]
            if any(exclude_predicates):
                continue
            if bad_name(field.verbose_name):
                suggested_name = suggest_name(field.verbose_name)
                errors.append(
                    Error(
                        f"Field “{field}” verbose_name should be lower cased.",
                        hint=f"Rename verbose_name from “{field.verbose_name}” to “{suggested_name}”.",
                        obj=model,
                    )
                )
    return errors
