import json
import pathlib

from crontab import CronTab


def test_crontab_order(settings):
    current_jobs = list(
        CronTab(
            tab="\n".join(
                json.loads(pathlib.Path(settings.ROOT_DIR).joinpath("clevercloud", "cron.json").read_bytes())
            )
        )
    )
    ordered_jobs = sorted(current_jobs, key=lambda j: (-j.frequency(), j.hour.parts, j.minute.parts))

    assert ordered_jobs == current_jobs
