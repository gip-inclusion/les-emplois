from huey.contrib.djhuey import db_task


@db_task()
def huey_notify_pole_employ(self, mode: str):
    return self._notify_pole_employ(mode)
