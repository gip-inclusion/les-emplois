import itertools
import json
import os
import os.path
import pathlib

from crontab import CronTab
from django.apps import apps
from django.conf import settings
from django.template import loader, loader_tags
from django.template.defaulttags import LoadNode

import itou.job_applications.enums as job_applications_enums


def iter_template_names():
    for template_conf in settings.TEMPLATES:
        for template_dir in template_conf["DIRS"]:
            for dirpath, _dirnames, filenames in os.walk(template_dir):
                for filename in filenames:
                    if filename == ".DS_Store" or filename.endswith(".orig"):
                        # Ignore macOS hidden files & merge .orig files
                        continue
                    yield os.path.relpath(os.path.join(dirpath, filename), template_dir)


def test_crontab_order(settings):
    current_jobs = list(
        CronTab(
            tab="\n".join(
                json.loads(pathlib.Path(settings.ROOT_DIR).joinpath("clevercloud", "cron.json").read_bytes())
            )
        )
    )
    ordered_jobs = sorted(current_jobs, key=lambda j: (-j.frequency(), j.hour.parts, j.minute.parts))

    assert ordered_jobs == current_jobs


def test_unused_templates():
    APP_TEMPLATES = [
        # Django
        "403.html",
        "404.html",
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
        "title_prevstep",
        "title_content",
        "title_messages",
        "title_extra",
        "content",
        "script",
    ]
    errors = []
    for template_name in iter_template_names():
        node_list = loader.get_template(template_name).template.nodelist
        if len(node_list) == 1 and isinstance(node_list[0], loader_tags.ExtendsNode):
            node_list = node_list[0].nodelist
        blocks = []
        loads = []
        for node in node_list:
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
            if loads != sorted(loads):
                errors.append((template_name, f"Unsorted loads: {loads}"))
    assert sorted(errors) == []  # Group errors by template_name
