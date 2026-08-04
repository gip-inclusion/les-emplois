import datetime

import pytest
from django.core.management import call_command
from freezegun import freeze_time

from itou.insertion.enums import OrientationStatus
from tests.insertion.factories import OrientationFactory


DORA_STATUS_URL = "https://dora-api/api/emplois/orientations/status/"


def status_item(uid, status, *, processing_date, updated_at):
    return {
        "emplois_sync_uid": str(uid),
        "status": status,
        "processing_date": processing_date,
        "updated_at": updated_at,
    }


def paginated(results, *, next_url=None):
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


@pytest.fixture(name="dora_settings")
def dora_settings_fixture(settings):
    settings.DORA_API_BASE_URL = "https://dora-api"
    settings.DORA_API_TOKEN = "token"


def test_updates_existing_orientation_status(dora_settings, respx_mock):
    with freeze_time("2026-07-01"):
        orientation = OrientationFactory(status=OrientationStatus.PENDING)
    respx_mock.get(DORA_STATUS_URL).respond(
        200,
        json=paginated(
            [
                status_item(
                    orientation.id,
                    OrientationStatus.ACCEPTED,
                    processing_date="2026-07-20T09:30:00+00:00",
                    updated_at="2026-07-20T09:30:00+00:00",
                )
            ]
        ),
    )

    call_command("sync_orientation_statuses", wet_run=True)

    orientation.refresh_from_db()
    assert orientation.status == OrientationStatus.ACCEPTED
    assert orientation.processing_date == datetime.datetime(2026, 7, 20, 9, 30, tzinfo=datetime.UTC)
    assert orientation.dora_status_updated_at == datetime.datetime(2026, 7, 20, 9, 30, tzinfo=datetime.UTC)
    assert orientation.updated_at == datetime.datetime(2026, 7, 20, 9, 30, tzinfo=datetime.UTC)


def test_null_processing_date_is_synced(dora_settings, respx_mock):
    with freeze_time("2026-01-01"):
        orientation = OrientationFactory(
            status=OrientationStatus.PENDING,
            processing_date=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )
    respx_mock.get(DORA_STATUS_URL).respond(
        200,
        json=paginated(
            [
                status_item(
                    orientation.id,
                    OrientationStatus.EXPIRED,
                    processing_date=None,
                    updated_at="2026-07-20T10:00:00+00:00",
                )
            ]
        ),
    )

    call_command("sync_orientation_statuses", wet_run=True)

    orientation.refresh_from_db()
    assert orientation.status == OrientationStatus.EXPIRED
    assert orientation.processing_date is None
    assert orientation.updated_at == datetime.datetime(2026, 7, 20, 10, 0, tzinfo=datetime.UTC)


def test_doesnt_update_more_recent_emplois(dora_settings, respx_mock, caplog):
    more_recent_datetime = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    with freeze_time(more_recent_datetime):
        orientation = OrientationFactory(status=OrientationStatus.PENDING)
    respx_mock.get(DORA_STATUS_URL).respond(
        200,
        json=paginated(
            [
                status_item(
                    orientation.id,
                    OrientationStatus.ACCEPTED,
                    processing_date="2026-07-20T09:30:00+00:00",
                    updated_at="2026-07-20T09:30:00+00:00",
                )
            ]
        ),
    )

    call_command("sync_orientation_statuses", wet_run=True)

    orientation.refresh_from_db()
    # Nothing changed
    assert orientation.status == OrientationStatus.PENDING
    assert orientation.dora_status_updated_at is None
    assert orientation.updated_at == more_recent_datetime
    assert f"Trying to update orientation={orientation.pk} with older DORA data" in caplog.messages


def test_first_run_has_no_updated_after(dora_settings, respx_mock):
    route = respx_mock.get(DORA_STATUS_URL).respond(200, json=paginated([]))

    call_command("sync_orientation_statuses", wet_run=True)

    assert "updated_after" not in route.calls.last.request.url.params


def test_incremental_run_uses_watermark(dora_settings, respx_mock):
    watermark = datetime.datetime(2026, 7, 20, 10, 0, tzinfo=datetime.UTC)
    OrientationFactory(dora_status_updated_at=watermark)
    route = respx_mock.get(DORA_STATUS_URL).respond(200, json=paginated([]))

    call_command("sync_orientation_statuses", wet_run=True)

    assert route.calls.last.request.url.params["updated_after"] == watermark.isoformat()


def test_dry_run_does_not_persist(dora_settings, respx_mock):
    orientation = OrientationFactory(status=OrientationStatus.PENDING)
    respx_mock.get(DORA_STATUS_URL).respond(
        200,
        json=paginated(
            [
                status_item(
                    orientation.id,
                    OrientationStatus.ACCEPTED,
                    processing_date="2026-07-20T10:00:00+00:00",
                    updated_at="2026-07-20T10:00:00+00:00",
                )
            ]
        ),
    )

    call_command("sync_orientation_statuses", wet_run=False)

    orientation.refresh_from_db()
    assert orientation.status == OrientationStatus.PENDING
    assert orientation.processing_date is None
    assert orientation.dora_status_updated_at is None


def test_unknown_uid_crashes_without_updating_anything(dora_settings, respx_mock):
    unknown_uid = "00000000-0000-0000-0000-000000000000"
    orientation = OrientationFactory(status=OrientationStatus.PENDING)
    respx_mock.get(DORA_STATUS_URL).respond(
        200,
        json=paginated(
            [
                status_item(
                    unknown_uid,
                    OrientationStatus.ACCEPTED,
                    processing_date="2026-07-20T10:00:00+00:00",
                    updated_at="2026-07-20T10:00:00+00:00",
                ),
                status_item(
                    orientation.id,
                    OrientationStatus.ACCEPTED,
                    processing_date="2026-07-20T10:00:00+00:00",
                    updated_at="2026-07-20T10:00:00+00:00",
                ),
            ]
        ),
    )

    with pytest.raises(RuntimeError, match=f"Unknown orientations from DORA: {unknown_uid}"):
        call_command("sync_orientation_statuses", wet_run=True)

    orientation.refresh_from_db()
    assert orientation.status == OrientationStatus.PENDING
