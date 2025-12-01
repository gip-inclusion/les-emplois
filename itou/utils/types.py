from psycopg.types.range import DateRange


class InclusiveDateRange(DateRange):
    def __init__(self, lower=None, upper=None, empty: bool = False):
        super().__init__(lower=lower, upper=upper, bounds="[]", empty=empty)
