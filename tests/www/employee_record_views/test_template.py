import pytest
from django.template import Context

from tests.employee_record.factories import EmployeeRecordWithProfileFactory
from tests.utils.testing import load_template


@pytest.mark.parametrize(
    "factory_kwargs",
    [
        pytest.param(
            {"with_classic_nir": True}, id="with_complete_profile"
        ),  # Classic NIR to ensure a NTT isn't needed
        pytest.param({"birth_country": None, "birth_place": None}, id="without_birth_country_nor_birth_place"),
        pytest.param({"with_hexa_address": None}, id="without_hexa_address"),
    ],
)
def test_send_back_dropdown(snapshot, factory_kwargs):
    template = load_template("employee_record/includes/send_back_dropdown.html")
    employee_record = EmployeeRecordWithProfileFactory(
        **{f"job_application__job_seeker__jobseeker_profile__{k}": v for k, v in factory_kwargs.items()}
    )

    html = template.render(
        Context({"csrf_token": "CSRF_TOKEN", "employee_record": employee_record, "extra_classes": ""})
    )
    normalized_html = (
        html.replace(
            f"/employee_record/create/{employee_record.job_application_id}",
            "/employee_record/create/[Pk of JobApplication]",
        )
        .replace(
            f"/employee_record/create_step_5/{employee_record.job_application_id}",
            "/employee_record/create_step_5/[Pk of JobApplication]",
        )
        .replace(f"sendBackRecordDropDown-{employee_record.pk}", "sendBackRecordDropDown-[Pk of EmployeeRecord]")
    )
    assert normalized_html == snapshot
