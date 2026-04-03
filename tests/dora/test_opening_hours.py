from itou.dora.opening_hours import format_osm_hours


def test_empty_string():
    assert format_osm_hours("") is None


def test_no_valid_schedule():
    # PH off alone produces an empty schedule
    assert format_osm_hours("PH off") is None


def test_invalid_string_returns_none():
    assert format_osm_hours("not valid at all") is None


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
