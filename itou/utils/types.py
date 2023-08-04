from psycopg.types.range import DateRange


class InclusiveDateRange(DateRange):
    def __init__(self, lower=None, upper=None):
        super().__init__(lower=lower, upper=upper, bounds="[]")
