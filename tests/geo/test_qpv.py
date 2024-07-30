from dataclasses import dataclass

import django.contrib.gis.geos as gis_geos
import pytest

from itou.geo.models import QPV
from itou.geo.utils import coords_to_geometry
from tests.geo.factories import QPVFactory


@dataclass
class _BadCoordsType:
    geom: str


@dataclass
class _MaybeCoordsType:
    coords: gis_geos.Point


@dataclass
class _GoodCoordsType:
    geom: gis_geos.Point


@pytest.fixture(autouse=True)
def qpv():
    for code in ["QP093028", "QP075019"]:
        QPVFactory(code=code)


def test_user_in_qpv():
    # Somewhere in QPV QP093028 (Aubervilliers)
    qpv = QPV.in_qpv(
        _GoodCoordsType(
            geom=coords_to_geometry("48.917735", "2.387311"),
        )
    )

    assert qpv is not None
    assert "QP093028" == qpv.code


def test_user_not_in_qpv():
    # Somewhere not in a QPV near Aubervilliers
    assert (
        QPV.in_qpv(
            _GoodCoordsType(geom=coords_to_geometry("48.899", "2.412")),
        )
        is None
    )


def test_obj_with_custom_coords_field():
    # Somewhere in QPV QP075019 (Paris 20e)
    qpv = QPV.in_qpv(
        _MaybeCoordsType(
            coords=coords_to_geometry("48.85592", "2.41299"),
        ),
        geom_field="coords",
    )

    assert qpv is not None
    assert "QP075019" == qpv.code


def test_obj_without_coords():
    with pytest.raises(ValueError):
        QPV.in_qpv("A str has no coords")


def test_obj_with_bad_coords_type():
    with pytest.raises(ValueError):
        QPV.in_qpv(_BadCoordsType(geom="A str is not a Point"))


def test_dunder_contains():
    qpv = QPV.objects.get(code="QP093028")
    in_qpv = coords_to_geometry("48.917735", "2.387311")
    not_in_qpv = coords_to_geometry("48.899", "2.412")

    assert in_qpv in qpv
    assert not_in_qpv not in qpv
