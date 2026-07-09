import pytest

from itou.insertion.opening_hours import format_osm_hours


@pytest.mark.parametrize("value", ["", "PH off", "not valid at all"])
def test_returns_none_for_invalid_input(value):
    assert format_osm_hours(value) is None


def test_basic_weekdays():
    result = format_osm_hours("Mo-Fr 09:00-17:00")
    assert result is not None
    assert result["has_ph_off"] is False
    assert len(result["entries"]) == 5
    labels = [e["label"] for e in result["entries"]]
    assert labels == ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
    for entry in result["entries"]:
        assert entry["hours"] == "9h00 à 17h00"
        assert entry["comment"] is None


def test_with_ph_off():
    result = format_osm_hours("Mo-Fr 09:00-17:00; PH off")
    assert result is not None
    assert result["has_ph_off"] is True
    assert len(result["entries"]) == 5


def test_day_off_excluded():
    result = format_osm_hours("Mo-Fr 09:00-17:00; Sa off")
    assert result is not None
    assert len(result["entries"]) == 5
    labels = [e["label"] for e in result["entries"]]
    assert "Samedi" not in labels


def test_multiple_time_ranges():
    result = format_osm_hours("Mo 09:00-12:00,14:00-17:00")
    assert result is not None
    assert len(result["entries"]) == 1
    assert result["entries"][0]["label"] == "Lundi"
    # sorted: 09:00-12:00 before 14:00-17:00
    assert result["entries"][0]["hours"] == "9h00 à 12h00 - 14h00 à 17h00"


def test_with_comment():
    result = format_osm_hours('Mo 09:00-12:00 "Sur rendez-vous"')
    assert result is not None
    assert len(result["entries"]) == 1
    assert result["entries"][0]["comment"] == "Sur rendez-vous"


def test_individual_days_in_order():
    result = format_osm_hours("We 14:00-18:00; Mo 09:00-12:00")
    assert result is not None
    assert len(result["entries"]) == 2
    # entries must be sorted by day index (Monday=0 before Wednesday=2)
    assert result["entries"][0]["label"] == "Lundi"
    assert result["entries"][1]["label"] == "Mercredi"


def test_time_formatting():
    # Verify the French time format: leading zero stripped, 'h' separator
    result = format_osm_hours("Mo 08:00-09:30")
    assert result is not None
    assert result["entries"][0]["hours"] == "8h00 à 9h30"


def test_complex_case():
    result = format_osm_hours(
        """
        Mo 08:30-12:00,13:30-16:00 open "Sans rendez-vous";
        Tu-Th 08:30-12:00; Fr 10:00-11:00 open "Sans rendez-vous";
        PH off"
        """
    )

    assert len(result["entries"]) == 5
    assert result["entries"][0] == {
        "comment": "Sans rendez-vous",
        "hours": "8h30 à 12h00 - 13h30 à 16h00",
        "label": "Lundi",
    }
    assert result["entries"][1] == {"comment": None, "hours": "8h30 à 12h00", "label": "Mardi"}
    assert result["entries"][2] == {"comment": None, "hours": "8h30 à 12h00", "label": "Mercredi"}
    assert result["entries"][3] == {"comment": None, "hours": "8h30 à 12h00", "label": "Jeudi"}
    assert result["entries"][4] == {"comment": "Sans rendez-vous", "hours": "10h00 à 11h00", "label": "Vendredi"}
    assert result["has_ph_off"] is True


def test_comma_separated_rules_with_closed():
    result = format_osm_hours(
        "Mo 09:00-21:00 open, Tu 09:00-21:00 open, We 09:00-21:00 open, "
        "Th 09:00-21:00 open, Fr 09:00-21:00 open, Sa 09:00-21:00 open, "
        "Su closed; PH closed"
    )
    assert result is not None
    assert result["has_ph_off"] is True
    labels = [e["label"] for e in result["entries"]]
    assert labels == ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
    for entry in result["entries"]:
        assert entry["hours"] == "9h00 à 21h00"


def test_open_without_times():
    result = format_osm_hours(
        "Mo 08:30-12:00,13:30-18:00 open, Tu 08:30-12:00,13:30-18:00 open, "
        "We 08:30-12:00,13:30-18:00 open, Th 13:30-18:00 open, Fr 13:30-18:00 open, "
        "Sa open, Su open; Aug closed"
    )
    assert result is not None
    labels = [e["label"] for e in result["entries"]]
    assert labels == ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    hours = {e["label"]: e["hours"] for e in result["entries"]}
    assert hours["Lundi"] == "8h30 à 12h00 - 13h30 à 18h00"
    assert hours["Jeudi"] == "13h30 à 18h00"
    assert hours["Samedi"] == "ouvert"
    assert hours["Dimanche"] == "ouvert"
    assert result["comments"] == ["Fermé en août"]


def test_month_off_comments():
    result = format_osm_hours("Mo-Fr 09:00-17:00; Jul-Aug off")
    assert result is not None
    assert result["comments"] == ["Fermé de juillet à août"]

    result = format_osm_hours("Mo-Fr 09:00-17:00; Jan,Feb off")
    assert result is not None
    assert result["comments"] == ["Fermé en janvier, février"]


def test_date_range_off_comments():
    result = format_osm_hours("Mo-Fr 07:30-18:30 open; Aug closed; Dec 25-Jan 1 closed")
    assert result is not None
    assert result["comments"] == ["Fermé en août", "Fermé du 25 décembre au 1er janvier"]

    result = format_osm_hours("Mo-Fr 09:00-17:00; Dec 20-31 off")
    assert result is not None
    assert result["comments"] == ["Fermé du 20 au 31 décembre"]

    result = format_osm_hours("Mo-Fr 09:00-17:00; Dec 25 off")
    assert result is not None
    assert result["comments"] == ["Fermé le 25 décembre"]
