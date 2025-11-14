import functools

from itou.utils import iso_standards


@functools.total_ordering
class NIR:
    def __init__(self, value: str):
        self.value = str(value) if value else None

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"NIR({self.value})"

    def __bool__(self):
        return bool(self.value)

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return self.value < other.value

    @property
    def sex(self) -> iso_standards.Sex:
        match self.value[0]:
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
        return int(self.value[1:3])

    @property
    def birth_month(self) -> int:
        return int(self.value[3:5])
