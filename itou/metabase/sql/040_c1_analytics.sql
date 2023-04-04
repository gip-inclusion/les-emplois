select
    cav.date,
    cav.type_detail,
    cav.value,
    lag(cav.value) over (
        partition by cav.type_detail
        order by
            cav.date
    ) as prev_value,
    cav.value - lag(cav.value) over (
        partition by cav.type_detail
        order by
            cav.date
    ) as delta
from
    c1_analytics_v0 as cav
