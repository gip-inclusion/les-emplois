from huey.contrib.djhuey import db_task


@db_task()
def huey_notify_pole_emploi(job_application):
    return job_application.approval.notify_pole_emploi()
