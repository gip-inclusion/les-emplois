from itoutils.django.decoupage_administratif.admin_division_parsing import get_division_label
from itoutils.django.decoupage_administratif.models import EPCI, City, Department


def bulk_load_division_labels(eligibility_zones_list: list[list[str] | None]) -> list[str]:
    codes = {code for zones in eligibility_zones_list if zones for code in zones}

    departments = dict(Department.objects.filter(code__in=codes).values_list("code", "name"))
    cities = {
        code: f"{name} ({department})"
        for code, name, department in City.objects.filter(code__in=codes).values_list("code", "name", "department")
    }
    epcis = dict(EPCI.objects.filter(code__in=codes).values_list("code", "name"))

    def label_for_code(code: str) -> str:
        return departments.get(code) or cities.get(code) or epcis.get(code) or get_division_label([code])

    def label_for_zones(zones: list[str]) -> str:
        return ", ".join(label for code in zones if (label := label_for_code(code)))

    return [get_division_label(zones) if zones is None else label_for_zones(zones) for zones in eligibility_zones_list]
