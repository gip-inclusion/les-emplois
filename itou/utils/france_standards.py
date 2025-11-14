import datetime
import functools
import re

from itou.utils import iso_standards


@functools.total_ordering
class NIR:
    FORMAT_RE = re.compile(
        r"""
        ^
        (?P<sex>[1-478])
        (?P<birth_year>\d{2})
        (?P<birth_month>0[1-9]|1[0-2]|[2-3]\d|4[0-2]|[5-9]\d)
        (?P<birth_place>
          (?:
            (?P<birth_department_mainland>0[1-9]|[1-8]\d|9[0-6]|2[AB])
            (?P<birth_city_mainland>00[1-9]|0[1-9]\d|[1-9]\d{2})
          ) | (?:
            (?P<birth_department_overseas>9[78]\d)
            (?P<birth_city_overseas>0[1-9]|[1-9]\d)
          ) | (?:
            99
            (?P<birth_country>00[1-9]|0[1-9]\d|[1-9]\d{2})
          )
        )
        (?P<birth_order>00[1-9]|0[1-9]\d|[1-9]\d{2})
        (?P<control_key>0[1-9]|[1-8]\d|9[0-7])
        $
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def __init__(self, value: str):
        if not value:
            self.value = None
            return
        # Normalize the value by removing whitespace and using uppercase for Corsica department identifier
        self.value = str(value).strip().replace(" ", "").upper()
        self._match = self.FORMAT_RE.match(self.value)

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"NIR({self.value})"

    def __hash__(self):
        return hash(self.value)

    def __bool__(self):
        return bool(self.value)

    def __len__(self):
        return len(self.value)

    def __lt__(self, other):
        if isinstance(other, self.__class__):
            return self.value < other.value
        if isinstance(other, str):
            return self.value < other
        return NotImplemented

    @property
    def sex(self) -> iso_standards.Sex:
        match self._match["sex"]:
            case "1" | "3" | "7":
                return iso_standards.Sex.MALE
            case "2" | "4" | "8":
                return iso_standards.Sex.FEMALE
            case "9":
                raise ValueError('"9" is not a valid value for the NIR sex part')
            case _:
                return iso_standards.Sex.NOT_KNOWN

    @property
    def birth_year(self) -> int:
        return int(self._match["birth_year"])

    @property
    def birth_month(self) -> int | None:
        birth_month = int(self._match["birth_month"])
        if 1 <= birth_month <= 12:
            return birth_month
        if 31 <= birth_month <= 42:  # « pseudo-fictifs » months
            return birth_month - 30
        return None

    @property
    def birth_place(self) -> str:
        # TODO: Return (Country, City)
        return self._match["birth_place"]

    @property
    def birth_order(self) -> int:
        return int(self._match["birth_order"])

    @property
    def control_key(self) -> int:
        return int(self._match["control_key"])

    @property
    def parts(self) -> tuple:
        return (
            self._match["sex"],
            self._match["birth_year"],
            self._match["birth_month"],
            self._match["birth_place"][:2],
            self._match["birth_place"][2:],
            self._match["birth_order"],
            self._match["control_key"],
        )

    def has_valid_format(self) -> bool:
        return self and bool(self._match)

    def has_valid_control_key(self) -> bool:
        nir_as_digits = self.value.replace("2A", "19").replace("2B", "18")
        return self.control_key == (97 - int(nir_as_digits[:13]) % 97)

    def is_valid(self) -> bool:
        return self.has_valid_format() and self.has_valid_control_key()

    def check_birth_date(self, birth_date: datetime.date) -> bool:
        is_ok = self.birth_year == birth_date.year % 100
        if self.birth_month:
            is_ok &= self.birth_month == birth_date.month
        return is_ok
