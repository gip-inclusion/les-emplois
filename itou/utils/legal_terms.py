import datetime
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone


@dataclass(frozen=True)
class TermsVersion:
    """Represents a specific version of the terms and conditions ('CGU')."""

    slug: str
    date: datetime.date
    template_name: str


def _get_terms_templates_dir():
    terms_dir = Path(settings.APPS_DIR) / "templates" / "static" / "legal" / "terms" / "versions"
    if not terms_dir.exists():
        raise ImproperlyConfigured("'CGU' templates directory not found.")
    return terms_dir


@cache
def _load_terms_versions():
    """Return all available TermsVersion objects sorted by date (newest first), cached for the process lifetime."""
    terms_dir = _get_terms_templates_dir()
    versions = []
    for file_path in terms_dir.glob("*.html"):
        datestr_from_name = file_path.name.removesuffix(".html")
        try:
            date_value = datetime.date.fromisoformat(datestr_from_name)
        except ValueError:
            raise ImproperlyConfigured(f"Template file name “{file_path}” does not match the format 'YYYY-MM-DD.html")
        versions.append(
            TermsVersion(
                slug=datestr_from_name,
                date=date_value,
                template_name=f"static/legal/terms/versions/{file_path.name}",
            )
        )
    if not versions:
        raise ImproperlyConfigured(f"'CGU' not found: {terms_dir}")
    return sorted(versions, key=lambda version: version.date, reverse=True)


def get_terms_versions():
    """Return past and current TermsVersion objects sorted by date (newest first).

    Future versions of the terms already available are just ignored, they will be included when they become active.
    """
    today = timezone.localdate()
    return [version for version in _load_terms_versions() if version.date <= today]


def get_latest_terms_datetime():
    latest = get_terms_versions()[0]
    return timezone.make_aware(
        datetime.datetime.combine(latest.date, datetime.time.min),
        ZoneInfo(settings.TIME_ZONE),
    )


def get_terms_version(version_slug: str):
    return next((version for version in get_terms_versions() if version.slug == version_slug), None)
