import collections
import dataclasses
import enum
import operator
import typing
from collections import namedtuple

from django.db.models import Model, QuerySet

from itou.utils.python import Sentinel, dotteditemgetter, identity


type Accessor = collections.abc.Callable[[str], typing.Any]
type CollectionKey = tuple[str, ...]
type Converter = collections.abc.Callable[[typing.Any], typing.Any]
type ConverterMapping = collections.abc.Mapping[DataKey, Converter]
type DataKey = str | collections.abc.Iterable[str]
type ItemKey = tuple[str, ...]
type DiffItemData = collections.abc.MutableMapping[str, DataDiff]

NOT_SET = Sentinel()


class DiffItemKind(enum.Enum):
    ADDED = "ADDED"
    UPDATED = "UPDATED"
    REMOVED = "REMOVED"


DataDiff = namedtuple("DataDiff", ["before", "after"])


@dataclasses.dataclass(frozen=True, slots=True)
class DiffItem:
    kind: DiffItemKind
    key: tuple
    current_item: Model | None = None
    comparative_item: dict | None = None
    data: DiffItemData | None = None

    def label(self):
        label_parts = [f"{self.kind.value} item key={self.key!r}"]
        if self.current_item:
            label_parts.append(f"current_item={type(self.current_item).__name__}({self.current_item.pk})")
        if self.data:
            label_parts.append(f"data={list(self.data.keys())}")
        return " ".join(label_parts)


@dataclasses.dataclass(frozen=True, slots=True)
class CollectionStrategy:
    key: CollectionKey
    accessor: Accessor
    accessor_ignored_exceptions: tuple[type[Exception]]
    converters: ConverterMapping

    def make_key(self, item) -> ItemKey:
        """Compute the item's identifying key.

        Converters will also be called for each key components value to
        accommodate complex composite key without having to do shenanigans
        in calling code.
        """
        return tuple(self.convert_data(item, part) for part in self.key)

    def convert_data(self, item, attr_key: DataKey):
        """Get an item field's value using the accessor then call the converter for that item field.

        The function will use a sentinel value (NOT_SET) if the accessor raise
        an exception listed as to be ignored, that value will be passed to
        the converter to allow error handling.
        """
        item_attr = (attr_key,) if isinstance(attr_key, str) else attr_key
        try:
            item_value = self.accessor(*item_attr)(item)
        except self.accessor_ignored_exceptions:
            item_value = NOT_SET
        return self.converters.get(attr_key, identity)(item_value)

    def needed_fields(self):
        return {*self.key, *self.converters}


class CollectionDiffer:
    def __init__(
        self,
        current_collection: QuerySet,
        comparative_collection: collections.abc.Iterable[dict],
        key: str | list[str] | tuple[list[str], list[str]],
        watched_data: collections.abc.Mapping[str, DataKey],
        *,
        current_data_converters: ConverterMapping = None,
        comparative_data_converters: ConverterMapping = None,
    ):
        self.current_collection = current_collection
        self.comparative_collection = comparative_collection
        self.watched_data = watched_data

        normalized_keys = self._normalize_key(key)
        self.current_collection_strategy = CollectionStrategy(
            key=normalized_keys[0],
            accessor=operator.attrgetter,
            accessor_ignored_exceptions=(AttributeError,),
            converters=current_data_converters or {},
        )
        self.comparative_collection_strategy = CollectionStrategy(
            key=normalized_keys[1],
            accessor=dotteditemgetter,
            accessor_ignored_exceptions=(KeyError,),
            converters=comparative_data_converters or {},
        )
        self._summary_informations = {}

    def __iter__(self) -> collections.abc.Generator[DiffItem]:
        comparative_collection_keys = set()
        keys_updated = 0
        current_collection_data: dict[ItemKey, Model] = {
            self.current_collection_strategy.make_key(current_item): current_item
            for current_item in self.current_collection.only(
                *{*self.current_collection_strategy.needed_fields(), *self.watched_data}
            ).iterator()
        }

        for comparative_item in self.comparative_collection:
            item_key = self.comparative_collection_strategy.make_key(comparative_item)
            comparative_collection_keys.add(item_key)

            if item_key not in current_collection_data:  # ADDED
                yield DiffItem(
                    kind=DiffItemKind.ADDED,
                    key=item_key,
                    current_item=None,
                    comparative_item=comparative_item,
                    data=self._get_added_data(comparative_item),
                )
            else:  # UPDATED
                current_item = current_collection_data[item_key]
                if updated_data := self._get_updated_data(current_item, comparative_item):
                    yield DiffItem(
                        kind=DiffItemKind.UPDATED,
                        key=item_key,
                        current_item=current_item,
                        comparative_item=comparative_item,
                        data=updated_data,
                    )
                    keys_updated += 1

        current_collection_keys = set(current_collection_data)
        keys_removed = current_collection_keys - comparative_collection_keys
        for item_key in sorted(keys_removed):  # DELETED
            yield DiffItem(
                kind=DiffItemKind.REMOVED,
                key=item_key,
                current_item=current_collection_data[item_key],
                comparative_item=None,
                data=None,
            )

        self._summary_informations = {
            "current_collection_keys_count": len(current_collection_keys),
            "comparative_collection_keys_count": len(comparative_collection_keys),
            "common_keys_count": len(current_collection_keys & comparative_collection_keys),
            "added_keys_count": len(comparative_collection_keys - current_collection_keys),
            "updated_keys_count": keys_updated,
            "removed_keys_count": len(keys_removed),
        }

    @staticmethod
    def _normalize_key(key: str | list[str] | tuple[list[str], list[str]]) -> tuple[CollectionKey, CollectionKey]:
        """Normalize the key argument into a standard form.

        To ease usability and reduce boilerplate in code uses we
        allow the use of shortcut whe giving the key to the class:
            - "foo" -> (["foo"], ["foo"])
            - ["foo", "bar"] -> (["foo", "bar"], ["foo", "bar"])
        """
        if isinstance(key, str):
            return tuple([key]), tuple([key])
        if isinstance(key, list):
            return tuple(key), tuple(key)
        return tuple(key[0]), tuple(key[1])

    def _get_added_data(self, comparative_item: dict) -> DiffItemData:
        """Return the converted data difference between both side's items for an ADDED operation.

        For ADDED operation the before part of the `DataDiff` will always be `None`."""
        data: DiffItemData = {}

        for current_item_attr_key, comparative_item_attr_key in self.watched_data.items():
            comparative_item_converted_value = self.comparative_collection_strategy.convert_data(
                comparative_item, comparative_item_attr_key
            )
            data[current_item_attr_key] = DataDiff(None, comparative_item_converted_value)

        return data

    def _get_updated_data(
        self,
        current_item: Model,
        comparative_item: dict,
    ) -> DiffItemData:
        """Return the converted data difference between both side's items for an UPDATED operation."""
        data: DiffItemData = {}

        for current_item_attr_key, comparative_item_attr_key in self.watched_data.items():
            current_item_converted_value = self.current_collection_strategy.convert_data(
                current_item, current_item_attr_key
            )
            comparative_item_converted_value = self.comparative_collection_strategy.convert_data(
                comparative_item, comparative_item_attr_key
            )

            if current_item_converted_value != comparative_item_converted_value:
                data[current_item_attr_key] = DataDiff(current_item_converted_value, comparative_item_converted_value)

        return data

    def summary_label(self) -> str:
        if not self._summary_informations:
            return "No summary informations available"
        return f"SUMMARY {self.current_collection.model.__name__} " + " ".join(
            f"{k}={v}" for k, v in self._summary_informations.items()
        )


def if_not_set_converter(default):
    def f(value):
        return default if value is NOT_SET else value

    return f
