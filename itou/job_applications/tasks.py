from huey.contrib.djhuey import db_task


@db_task()
def huey_notify_pole_employ(job_application):
    return notify_pole_emploi_pass(job_application, job_application.job_seeker)
