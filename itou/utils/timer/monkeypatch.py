from itou.utils.timer.infos import timing


def install_sql_timing():
    from django.db.backends.utils import CursorWrapper

    origin_execute = CursorWrapper._execute_with_wrappers

    def _execute_with_wrappers(self, sql, params, many, executor):
        with timing():
            return origin_execute(self, sql, params, many, executor)

    CursorWrapper._execute_with_wrappers = _execute_with_wrappers
