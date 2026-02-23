import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from freezegun import freeze_time

from itou.utils import legal_terms
from itou.utils.legal_terms import (
    TermsVersion,
    _get_latest_terms_datetime_for_date,
    _get_terms_templates_dir,
    _get_terms_versions_for_date,
    _load_terms_versions,
    get_terms_versions,
)


@pytest.fixture(autouse=True)
def clear_terms_cache():
    _load_terms_versions.cache_clear()
    _get_terms_versions_for_date.cache_clear()
    _get_latest_terms_datetime_for_date.cache_clear()
    yield
    _load_terms_versions.cache_clear()
    _get_terms_versions_for_date.cache_clear()
    _get_latest_terms_datetime_for_date.cache_clear()


@pytest.fixture
def mocked_terms_templates_dir(settings, tmp_path):
    settings.APPS_DIR = tmp_path
    terms_dir = tmp_path / "templates" / "static" / "legal" / "terms" / "versions"
    terms_dir.mkdir(parents=True, exist_ok=True)
    return terms_dir


@pytest.fixture
def add_terms_templates(mocked_terms_templates_dir):
    def _add_many(*filenames):
        for filename in filenames:
            (mocked_terms_templates_dir / filename).write_text("<p>CGU</p>", encoding="utf-8")

    return _add_many


def test_get_terms_templates_dir_raises_when_missing(settings, tmp_path):
    settings.APPS_DIR = tmp_path
    with pytest.raises(ImproperlyConfigured, match="templates directory not found"):
        _get_terms_templates_dir()


def test_terms_templates_are_valid():
    terms_dir = _get_terms_templates_dir()
    found = False
    for file_path in terms_dir.glob("*.html"):
        datestr_from_name = file_path.name.removesuffix(".html")
        try:
            datetime.date.fromisoformat(datestr_from_name)
        except ValueError:
            raise ImproperlyConfigured(f"Template file name “{file_path}” does not match the format 'YYYY-MM-DD.html")
        found = True
    assert found, "'CGU' not found: {terms_dir}"


class TestLoadTermsVersions:
    def test_ignore_non_html_files(self, add_terms_templates):
        add_terms_templates("2025-10-09.html", "irrelevant.md")
        versions = _load_terms_versions()
        assert [version.slug for version in versions] == ["2025-10-09"]


class TestGetTermsVersions:
    @freeze_time("2025-06-01")
    def test_ignore_future_terms_and_keep_past_sorted(self, add_terms_templates):
        add_terms_templates(
            "2025-05-01.html", "2024-01-15.html", "2026-01-01.html", "2023-12-31.html", "2025-12-15.html"
        )
        versions = get_terms_versions()
        assert versions == sorted(versions, key=lambda version: version.date, reverse=True)
        assert [version.slug for version in versions] == ["2025-05-01", "2024-01-15", "2023-12-31"]


class TestGetLatestTermsDatetime:
    def test_get_latest_terms_datetime_uses_current_timezone(self, mocker):
        mocker.patch.object(
            legal_terms,
            "_get_terms_versions_for_date",
            return_value=[
                TermsVersion(slug="2025-02-12", date=datetime.date(2025, 2, 12), template_name="b.html"),
                TermsVersion(slug="2024-10-02", date=datetime.date(2024, 1, 1), template_name="a.html"),
            ],
        )
        latest_datetime = legal_terms.get_latest_terms_datetime()
        assert latest_datetime == datetime.datetime(2025, 2, 12, 0, 0, tzinfo=ZoneInfo(settings.TIME_ZONE))


class TestGetTermsVersion:
    def test_return_none_when_slug_is_not_found(self):
        assert legal_terms.get_terms_version("1999-12-12") is None
