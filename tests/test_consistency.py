import collections
import inspect
import itertools
import json
import os
import os.path
import pathlib

from crontab import CronTab
from django.apps import apps
from django.conf import settings
from django.core import management
from django.db.models.deletion import CASCADE, PROTECT
from django.db.models.fields.related import RelatedField
from django.template import loader, loader_tags
from django.template.defaulttags import LoadNode

import itou.job_applications.enums as job_applications_enums
from itou.antivirus.models import Scan
from itou.files.models import File


def iter_template_names():
    for template_conf in settings.TEMPLATES:
        for template_dir in template_conf["DIRS"]:
            for dirpath, _dirnames, filenames in os.walk(template_dir):
                for filename in filenames:
                    if filename == ".DS_Store" or filename.endswith(".orig"):
                        # Ignore macOS hidden files & merge .orig files
                        continue
                    yield os.path.relpath(os.path.join(dirpath, filename), template_dir)


def load_cron_items_from_json(settings):
    return list(
        CronTab(
            tab="\n".join(
                json.loads(pathlib.Path(settings.ROOT_DIR).joinpath("clevercloud", "cron.json").read_bytes())
            )
        )
    )


def test_crontab_order(settings):
    current_jobs = load_cron_items_from_json(settings)
    ordered_jobs = sorted(current_jobs, key=lambda j: (-j.frequency(), j.hour.parts, j.minute.parts))

    assert ordered_jobs == current_jobs


def test_sentry_monitor_cron_config(settings):
    cron_items = load_cron_items_from_json(settings)
    checked_commands = set()
    for cmd_name, app_name in management.get_commands().items():
        command_handle = management.load_command_class(app_name, cmd_name).handle
        if closure_nonlocals_self := inspect.getclosurevars(command_handle).nonlocals.get("self"):
            if monitor_config := getattr(closure_nonlocals_self, "monitor_config", None):
                # This command is likely monitored by Sentry
                schedule = monitor_config["schedule"]
                assert schedule["type"] == "crontab"
                for cron_item in cron_items:
                    if cron_item.command and cmd_name in cron_item.command:
                        assert schedule["value"] == cron_item.slices.render()
                        checked_commands.add(cmd_name)

    # Make sure our shenanigans worked and we actually checked something
    assert checked_commands


def test_unused_templates():
    APP_TEMPLATES = [
        # Django
        "403.html",
        "404.html",
        "429.html",
        "500.html",
        "django/forms/widgets/password.html",
        # Django allauth
        "account/account_inactive.html",
        "account/email_confirm.html",
        "account/logout.html",
        "account/password_change.html",
        "account/password_reset.html",
        "account/password_reset_done.html",
        "account/password_reset_from_key.html",
        "account/password_reset_from_key_done.html",
        "account/verification_sent.html",
        "account/email/unknown_account_message.txt",
        "account/email/unknown_account_subject.txt",
        "account/email/email_confirmation_message.txt",
        "account/email/email_confirmation_signup_message.txt",
        "account/email/email_confirmation_subject.txt",
        "account/email/password_reset_key_message.txt",
        "account/email/password_reset_key_subject.txt",
        "account/messages/logged_in.txt",
        # django-bootstrap5
        "django_bootstrap5/form_errors.html",
        "django_bootstrap5/messages.html",
        "django_bootstrap5/widgets/radio_select.html",
        # Used in itou/siae_evaluations/models.py's Calendar model
        "siae_evaluations/default_calendar_html.html",
    ] + [
        # Cf RefuseWizardView
        f"apply/refusal_messages/{reason.value}.txt"
        for reason in job_applications_enums.RefusalReason
    ]

    template_names_to_check = set()
    for template_name in iter_template_names():
        if template_name not in APP_TEMPLATES:
            template_names_to_check.add(template_name)

    for dirpath, _dirnames, filenames in itertools.chain(
        os.walk(os.path.join(settings.ROOT_DIR, "config")), os.walk(settings.APPS_DIR)
    ):
        for filename in filenames:
            if template_names_to_check and filename.endswith((".py", ".html", ".txt")):
                with open(os.path.join(dirpath, filename)) as f:
                    file_content = f.read()
                for template_name in tuple(template_names_to_check):
                    if template_name in file_content:
                        template_names_to_check.remove(template_name)

    assert not template_names_to_check


def test_check_verbose_name_lower():
    def bad_name(name):
        first_word, *rest = name.split()
        return first_word[0].isupper() and first_word not in {
            "CV",
            "DDETS",
            "GEIQ",
            "ID",
            "NIR",
            "NTT",
            "PASS",
            "QPV",
            "ROME",
            "SIAE",
            "URL",
            "ZRR",
        }

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
                    errors.append(f"Model {model} {fieldname} should be lower cased.")
        for field in model._meta.get_fields():
            exclude_predicates = [
                field.is_relation and field.auto_created,  # Reverse side of the relation
                field.is_relation and field.related_model is None,  # GenericForeignKey
            ]
            if any(exclude_predicates):
                continue
            if bad_name(field.verbose_name):
                errors.append(f"Field “{field}” verbose_name should be lower cased.")

    assert errors == []


def test_check_templates_ordering():
    EXPECTED_BLOCK_ORDER = [
        "title",
        "title_navinfo",
        "title_content",
        "title_messages",
        "title_extra",
        "content",
        "script",
    ]

    def iter_through_extends_node(nodelist):
        for node in nodelist:
            if isinstance(node, loader_tags.ExtendsNode):
                yield from node.nodelist
            else:
                yield node

    errors = []
    for template_name in iter_template_names():
        blocks = []
        loads = []
        for node in iter_through_extends_node(loader.get_template(template_name).template.nodelist):
            if isinstance(node, loader_tags.BlockNode) and node.name in EXPECTED_BLOCK_ORDER:
                blocks.append(node.name)
            if isinstance(node, LoadNode):
                loads.append(node.token.contents)
        if blocks:
            expected_order = [block for block in EXPECTED_BLOCK_ORDER if block in blocks]
            if blocks != expected_order:
                errors.append((template_name, f"Unsorted blocks: {blocks} ({expected_order=})"))
        if loads:
            for load in loads:
                if len(load.split()) != 2:
                    errors.append((template_name, f"One load per line expected: {load}"))
            if len(loads) != len(set(loads)):
                duplicates = sorted(load for load, count in collections.Counter(loads).items() if count != 1)
                errors.append((template_name, f"Duplicate loads found: {duplicates}"))
            if loads != sorted(loads):
                errors.append((template_name, f"Unsorted loads: {loads}"))
    assert sorted(errors) == []  # Group errors by template_name


def test_files_foreign_keys():
    models = apps.get_models()
    for model in models:
        file_related_fields = [
            f for f in model._meta.get_fields() if isinstance(f, RelatedField) and f.related_model == File
        ]
        for field in file_related_fields:
            expected_on_delete = CASCADE if model == Scan else PROTECT
            assert field.remote_field.on_delete == expected_on_delete, (
                f"{model.__module__}.{model.__name__}.{field.name} "
                f"has on_delete={field.remote_field.on_delete.__name__} "
                f"should be {expected_on_delete.__name__}"
            )
