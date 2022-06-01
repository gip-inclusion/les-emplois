from huey.contrib.djhuey import db_task


@db_task()
def huey_notify_pole_emploi(job_application):
    return job_application.notify_pole_emploi(with_delay=True)
