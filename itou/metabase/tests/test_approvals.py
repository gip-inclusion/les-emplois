from django.test import override_settings

from itou.approvals.factories import ApprovalFactory
from itou.metabase.management.commands._approvals import TABLE


@override_settings(METABASE_HASH_SALT="foobar2000")
def test_hashed_approval_number():
    approval = ApprovalFactory(number="999992012369")
    assert (
        TABLE.get(column_name="hash_numéro_pass_iae", input=approval)
        == "314b2d285803a46c89e09ba9ad4e23a52f2e823ad28343cdff15be0cb03fee4a"
    )
    approval.number = None
    assert (
        TABLE.get(column_name="hash_numéro_pass_iae", input=approval)
        == "8e728c4578281ea0b6a7817e50a0f6d50c995c27f02dd359d67427ac3d86e019"
    )
    approval.number = ""
    assert (
        TABLE.get(column_name="hash_numéro_pass_iae", input=approval)
        == "6cc868860cee823f0ffe0b3498bb4ebda51baa1b7858e2022f6590b0bd86c31c"
    )


@override_settings(SECRET_KEY="foobar2022")
def test_id_candidat_anonymisé():
    approval = ApprovalFactory(user__pk=18)
    assert TABLE.get(column_name="id_candidat_anonymisé", input=approval) == "4532819e6f4be94d2716bb5d5c6f61e7fd8bc4e3"
