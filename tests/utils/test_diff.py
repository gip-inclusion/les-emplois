import datetime
import uuid

import pytest
from django.utils import timezone

from itou.files.models import File
from itou.utils import diff, python
from tests.files.factories import FileFactory


@pytest.mark.parametrize(
    "key, expected",
    [
        pytest.param("foo", [("foo",), ("foo",)], id="same-single-key"),
        pytest.param(["foo", "bar"], [("foo", "bar"), ("foo", "bar")], id="same-composite-key"),
        pytest.param((["foo"], ["bar"]), [("foo",), ("bar",)], id="different-single-key"),
        pytest.param(
            (["foo", "fighters"], ["bar", "italia"]),
            [("foo", "fighters"), ("bar", "italia")],
            id="different-composite-key",
        ),
    ],
)
def test_collection_differ_key_normalization(key, expected):
    differ = diff.CollectionDiffer(None, None, key, None)
    assert [differ.current_collection_strategy.key, differ.comparative_collection_strategy.key] == expected


def test_collection_differ_simple_operations(snapshot):
    # Start - Both collections are empty
    differ = diff.CollectionDiffer(File.objects.all(), [], "key", watched_data={})
    assert list(differ) == []
    assert differ.summary_label() == snapshot(name="both collections empty")

    # A new objects is added
    comparative_data = {"key": uuid.uuid4()}
    differ = diff.CollectionDiffer(File.objects.all(), [comparative_data], "key", watched_data={})
    assert list(differ) == [
        diff.DiffItem(diff.DiffItemKind.ADDED, (comparative_data["key"],), None, comparative_data, data={}),
    ]
    assert differ.summary_label() == snapshot(name="one object added")

    # The object is updated
    file = FileFactory()  # Create the object like an import script would do
    comparative_data = {"key": file.key, "last_modified": timezone.now()}
    differ = diff.CollectionDiffer(
        File.objects.all(), [comparative_data], "key", watched_data={"last_modified": "last_modified"}
    )
    assert list(differ) == [
        diff.DiffItem(
            diff.DiffItemKind.UPDATED,
            (file.key,),
            file,
            comparative_data,
            data={"last_modified": diff.DataDiff(file.last_modified, comparative_data["last_modified"])},
        ),
    ]
    assert differ.summary_label() == snapshot(name="one object updated")

    # Finish - The object is removed
    differ = diff.CollectionDiffer(File.objects.all(), [], "key", watched_data={})
    assert list(differ) == [
        diff.DiffItem(diff.DiffItemKind.REMOVED, (file.key,), file, None, data=None),
    ]
    assert differ.summary_label() == snapshot(name="one object removed")


def test_collection_differ_watched_data():
    file = FileFactory()
    comparative_data = {"key": file.key, "updated_at": timezone.now()}

    differ = diff.CollectionDiffer(
        File.objects.all(), [comparative_data], "key", watched_data={"last_modified": "updated_at"}
    )
    assert list(differ) == [
        diff.DiffItem(
            diff.DiffItemKind.UPDATED,
            (file.key,),
            file,
            comparative_data,
            data={"last_modified": diff.DataDiff(file.last_modified, comparative_data["updated_at"])},
        ),
    ]


def test_collection_differ_data_converters():
    the_key = uuid.uuid4()
    file = FileFactory(key=str(the_key))  # Cast to str to test key's converter as str(UUID()) != UUID()
    comparative_data = {"key": the_key, "updated_at": timezone.now().isoformat()}

    differ = diff.CollectionDiffer(
        File.objects.all(),
        [comparative_data],
        "key",
        watched_data={"last_modified": "updated_at"},
        current_data_converters={"key": uuid.UUID},
        comparative_data_converters={"updated_at": datetime.datetime.fromisoformat},
    )
    assert list(differ) == [
        diff.DiffItem(
            diff.DiffItemKind.UPDATED,
            (the_key,),
            file,
            comparative_data,
            data={
                "last_modified": diff.DataDiff(
                    file.last_modified, datetime.datetime.fromisoformat(comparative_data["updated_at"])
                )
            },
        ),
    ]


def test_if_not_set_converter():
    expected = python.Sentinel()

    # Test falsy values
    assert diff.if_not_set_converter(expected)(None) is None
    assert diff.if_not_set_converter(expected)(False) is False
    assert diff.if_not_set_converter(expected)("") == ""
    assert diff.if_not_set_converter(expected)(0) == 0
    assert diff.if_not_set_converter(expected)([]) == []
    # Test truthy values
    assert diff.if_not_set_converter(expected)(True) is True
    assert diff.if_not_set_converter(expected)("foo") == "foo"
    assert diff.if_not_set_converter(expected)(42) == 42
    assert diff.if_not_set_converter(expected)([[]]) == [[]]

    # Test for missing (NOT_SET sentinel) value
    assert diff.if_not_set_converter(expected)(diff.NOT_SET) is expected
