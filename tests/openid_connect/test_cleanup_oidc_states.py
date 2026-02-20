import datetime

from django.core.management import call_command
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.openid_connect.constants import OIDC_STATE_CLEANUP
from itou.openid_connect.france_connect.models import FranceConnectState
from itou.openid_connect.pe_connect.models import PoleEmploiConnectState
from itou.openid_connect.pro_connect.models import ProConnectState


def test_cleanup(caplog):
    cutoff = timezone.now() - OIDC_STATE_CLEANUP - datetime.timedelta(hours=1)

    # Recent states to keep
    fc_recent = FranceConnectState.objects.create(state="fc_recent")
    pe_recent = PoleEmploiConnectState.objects.create(state="pe_recent")
    pc_recent = ProConnectState.objects.create(state="pc_recent")

    # Old states to delete
    FranceConnectState.objects.create(state="fc_old", created_at=cutoff)
    PoleEmploiConnectState.objects.create(state="pe_old", created_at=cutoff)
    ProConnectState.objects.bulk_create(
        [
            ProConnectState(state="pc_old_1", created_at=cutoff),
            ProConnectState(state="pc_old_2", created_at=cutoff - datetime.timedelta(hours=1)),
        ]
    )

    call_command("cleanup_oidc_states")

    for model, expected in (
        (FranceConnectState, [fc_recent]),
        (PoleEmploiConnectState, [pe_recent]),
        (ProConnectState, [pc_recent]),
    ):
        assertQuerySetEqual(model.objects.all(), expected)

    assert caplog.messages[:-1] == [
        "Deleted 1 obsolete FranceConnectState",
        "Deleted 1 obsolete PoleEmploiConnectState",
        "Deleted 2 obsolete ProConnectStates",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.openid_connect.management.commands.cleanup_oidc_states succeeded in"
    )
