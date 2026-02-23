"""Tests for legal_terms utils functions."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from freezegun import freeze_time

from itou.utils import legal_terms
from itou.utils.legal_terms import (
    TermsVersion,
    _get_terms_templates_dir,
    _load_terms_versions,
    get_terms_versions,
)


@pytest.fixture(autouse=True)
def clear_terms_cache():
    _load_terms_versions.cache_clear()
    yield
    _load_terms_versions.cache_clear()


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


class TestGetTermsTemplatesDir:
    def test_raises_when_missing(self, settings, tmp_path):
        settings.APPS_DIR = tmp_path
        with pytest.raises(ImproperlyConfigured, match="templates directory not found"):
            _get_terms_templates_dir()


class TestLoadTermsVersions:
    def test_that_everything_is_actually_well_configured_without_mock(self):
        assert _load_terms_versions()

    def test_cache_is_used(self, add_terms_templates, mocker):
        add_terms_templates("2025_10_09.html")
        get_terms_templates_dir_spy = mocker.spy(legal_terms, "_get_terms_templates_dir")

        first_call = _load_terms_versions()
        second_call = _load_terms_versions()

        assert first_call is second_call
        get_terms_templates_dir_spy.assert_called_once_with()

    def test_ignore_non_html_files(self, add_terms_templates):
        add_terms_templates("2025_10_09.html", "irrelevant.md")
        versions = _load_terms_versions()
        assert [version.slug for version in versions] == ["2025-10-09"]

    def test_raise_when_no_template_is_available(self, mocked_terms_templates_dir):
        with pytest.raises(ImproperlyConfigured, match="'CGU' not found"):
            _load_terms_versions()


class TestGetTermsVersions:
    @freeze_time("2025-06-01")
    def test_ignore_future_terms_and_keep_past_sorted(self, add_terms_templates):
        add_terms_templates(
            "2025_05_01.html", "2024_01_15.html", "2026_01_01.html", "2023_12_31.html", "2025_12_15.html"
        )
        versions = get_terms_versions()
        assert versions == sorted(versions, key=lambda version: version.date)
        assert [version.slug for version in versions] == ["2023-12-31", "2024-01-15", "2025-05-01"]


def _terms_versions_fixture():
    return [
        TermsVersion(slug="2024-10-02", date=datetime.date(2024, 1, 1), template_name="a.html"),
        TermsVersion(slug="2025-02-12", date=datetime.date(2025, 2, 12), template_name="b.html"),
    ]


class TestGetLatestTermsDatetime:
    def test_get_latest_terms_datetime_uses_current_timezone(self, mocker):
        versions = _terms_versions_fixture()
        mocker.patch.object(legal_terms, "get_terms_versions", return_value=versions)
        latest_datetime = legal_terms.get_latest_terms_datetime()
        assert latest_datetime == datetime.datetime(2025, 2, 12, 0, 0, tzinfo=ZoneInfo(settings.TIME_ZONE))


class TestGetTermsVersion:
    def test_return_matching_item_with_provided_versions(self):
        versions = _terms_versions_fixture()
        version = legal_terms.get_terms_version("2025-02-12", all_versions=versions)
        assert version == versions[1]

    def test_return_none_when_slug_is_not_found(self):
        versions = _terms_versions_fixture()
        version = legal_terms.get_terms_version("2026-01-04", all_versions=versions)
        assert version is None

    def test_use_get_terms_versions_when_all_versions_omitted(self, mocker):
        versions = _terms_versions_fixture()
        get_terms_versions_mock = mocker.patch.object(legal_terms, "get_terms_versions", return_value=versions)
        version = legal_terms.get_terms_version("2024-10-02")
        assert version == versions[0]
        get_terms_versions_mock.assert_called_once_with()
