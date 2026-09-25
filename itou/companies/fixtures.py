import datetime

from django.utils import timezone

from itou.companies.models import Contract


def update_contract_end_dates():
    # The asserts are here to ensure nobody changes the dates in companies__contract.json without updating this script
    assert Contract.objects.filter(end_date__isnull=False).count() == 6

    today = timezone.localdate()
    # Already ended contracts
    updated = Contract.objects.filter(end_date="2024-01-01").update(end_date=today - datetime.timedelta(days=30))
    assert updated == 1
    # Soon to end contracts
    updated = Contract.objects.filter(end_date="2025-01-01").update(end_date=today + datetime.timedelta(days=15))
    assert updated == 4
    # Contacts ending in a long time
    updated = Contract.objects.filter(end_date="2026-01-01").update(end_date=today + datetime.timedelta(days=60))
    assert updated == 1
