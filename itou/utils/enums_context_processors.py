import itou.approvals.enums as approvals_enums
import itou.job_applications.enums as job_aplication_enums


def expose_enums(*args):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/4.1/ref/templates/api/#using-requestcontext
    """

    return {
        "ApprovalOrigin": approvals_enums.Origin,
        "JobApplicationOrigin": job_aplication_enums.Origin,
        "SenderKind": job_aplication_enums.SenderKind,
    }
