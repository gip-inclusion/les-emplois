import pytest

from itou.utils.python import dotteditemgetter


def test_dotteditemgetter():
    item = {
        "a": "value of a",
        "b": {
            "1": {
                "a": "value of b.1.a",
            }
        },
        "c": {
            "1": "value of c.1",
            "2": [],
        },
    }

    # Test with single item name
    assert dotteditemgetter("a")(item) == "value of a"
    assert dotteditemgetter("b")(item) == {
        "1": {
            "a": "value of b.1.a",
        }
    }
    assert dotteditemgetter("b.1")(item) == {
        "a": "value of b.1.a",
    }
    assert dotteditemgetter("b.1.a")(item) == "value of b.1.a"
    assert dotteditemgetter("c.2")(item) == []

    # Test with multiple item names
    assert dotteditemgetter("a", "b.1.a")(item) == ("value of a", "value of b.1.a")
    assert dotteditemgetter("a", "b.1", "c.1")(item) == ("value of a", {"a": "value of b.1.a"}, "value of c.1")

    # Test errors
    with pytest.raises(KeyError, match="'z'"):
        dotteditemgetter("z")(item)
    with pytest.raises(KeyError, match="'404'"):
        dotteditemgetter("c.404")(item)
    with pytest.raises(TypeError, match="'NoneType' object is not subscriptable"):
        dotteditemgetter("whatever")(None)

    # Test unsupported features
    with pytest.raises(TypeError, match="list indices must be integers or slices, not str"):
        dotteditemgetter("0")([])
    with pytest.raises(TypeError, match="list indices must be integers or slices, not str"):
        dotteditemgetter("c.2.0")(item)
