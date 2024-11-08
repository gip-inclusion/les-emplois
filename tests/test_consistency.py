import itertools
import json
import os
import os.path
import pathlib

from crontab import CronTab
from django.conf import settings

import itou.job_applications.enums as job_applications_enums


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
        # Cf JobApplicationRefuseView
        f"apply/refusal_messages/{reason.value}.txt"
        for reason in job_applications_enums.RefusalReason
    ]

    template_names_to_check = set()
    for template_conf in settings.TEMPLATES:
        for template_dir in template_conf["DIRS"]:
            for dirpath, _dirnames, filenames in os.walk(template_dir):
                for filename in filenames:
                    template_name = os.path.relpath(os.path.join(dirpath, filename), template_dir)
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
