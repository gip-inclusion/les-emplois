import datetime
import operator
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone


def bypass_terms_acceptance(view_func):
    """Decorator marking a view as exempt from the terms acceptance check.

    Works like Django's @login_not_required: sets an attribute on the view
    function that TermsAcceptanceMiddleware inspects.
    """
    view_func._bypass_terms_acceptance = True
    return view_func


def _get_terms_templates_dir():
    terms_dir = Path(settings.APPS_DIR) / "templates" / "static" / "legal" / "terms" / "versions"
    if not terms_dir.exists():
        raise ImproperlyConfigured("'CGU' templates directory not found.")
    return terms_dir


@dataclass(frozen=True)
class TermsVersion:
    """Represents a specific version of the terms and conditions ('CGU')."""

    slug: str
    date: datetime.date
    template_name: str


@cache
def _load_terms_versions():
    """Return all available TermsVersion objects sorted by date (newest first), cached for the process lifetime."""
    terms_dir = _get_terms_templates_dir()
    versions = []
    for file_path in terms_dir.glob("*.html"):
        datestr_from_name = file_path.name.removesuffix(".html")
        versions.append(
            TermsVersion(
                slug=datestr_from_name,
                date=datetime.date.fromisoformat(datestr_from_name),
                template_name=f"static/legal/terms/versions/{file_path.name}",
            )
        )
    return sorted(versions, key=operator.attrgetter("date"), reverse=True)


@lru_cache(maxsize=1)
def _get_terms_versions_for_date(today):
    """Return past and current TermsVersion objects for the given date, cached per day.

    The maxsize=1 cache is naturally evicted at midnight when today's date changes.
    """
    return [version for version in _load_terms_versions() if version.date <= today]


def get_terms_versions():
    """Return past and current TermsVersion objects sorted by date (newest first).

    Future versions of the terms already available are just ignored, they will be included when they become active.
    """
    return _get_terms_versions_for_date(timezone.localdate())


@lru_cache(maxsize=1)
def _get_latest_terms_datetime_for_date(today):
    """Return the latest terms datetime for the given date, cached per day."""
    latest = _get_terms_versions_for_date(today)[0]
    return timezone.make_aware(
        datetime.datetime.combine(latest.date, datetime.time.min),
        ZoneInfo(settings.TIME_ZONE),
    )


def get_latest_terms_datetime():
    return _get_latest_terms_datetime_for_date(timezone.localdate())


def get_terms_version(version_slug):
    return next((version for version in get_terms_versions() if version.slug == version_slug), None)
