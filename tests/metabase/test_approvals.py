from django.test import override_settings

from itou.metabase.tables.approvals import TABLE
from tests.approvals.factories import ApprovalFactory


@override_settings(METABASE_HASH_SALT="foobar2000")
def test_hashed_approval_number():
    approval = ApprovalFactory(number="XXXXX2012369")

    assert (
        TABLE.get(column_name="hash_numéro_pass_iae", input=approval)
        == "7cc9da292b108e91aa40f7287b990daeca22b296e68ee5e0457a89c97a282c27"
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
