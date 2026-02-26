import datetime
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone


TERMS_TEMPLATE_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\.html$")


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
    """Return all available TermsVersion objects sorted by date (oldest first), cached for the process lifetime."""
    terms_dir = _get_terms_templates_dir()
    versions = []
    for file_path in terms_dir.glob("*.html"):
        match = TERMS_TEMPLATE_PATTERN.match(file_path.name.replace("_", "-"))
        if not match:
            msg = "Template file name does not match the expected format 'YYYY_MM_DD.html': {file_name}"
            raise ImproperlyConfigured(msg.format(file_name=file_path.name))
        date_value = datetime.date.fromisoformat(match.group("date"))
        versions.append(
            TermsVersion(
                slug=match.group("date"),
                date=date_value,
                template_name=f"static/legal/terms/versions/{file_path.name}",
            )
        )
    if not versions:
        msg = "'CGU' not found: {directory}"
        raise ImproperlyConfigured(msg.format(directory=terms_dir))
    return sorted(versions, key=lambda version: version.date)


def get_terms_versions():
    """Return past and current TermsVersion objects sorted by date (oldest first).

    Future versions of the terms already available are just ignored, they will be included when they become active.
    """
    today = timezone.now().date()
    return [version for version in _load_terms_versions() if version.date <= today]


def get_latest_terms_datetime():
    latest = get_terms_versions()[-1]
    return timezone.make_aware(
        datetime.datetime.combine(latest.date, datetime.time.min),
        ZoneInfo(settings.TIME_ZONE),
    )


def get_terms_version(version_slug: str, *, all_versions=None):
    """Retrieve a specific version from the list of all 'CGU' versions."""
    if not all_versions:
        all_versions = get_terms_versions()
    return next((version for version in all_versions if version.slug == version_slug), None)
