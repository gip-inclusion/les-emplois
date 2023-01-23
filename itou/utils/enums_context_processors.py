import itou.job_applications.enums as job_aplication_enums


def expose_enums(*args):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/4.1/ref/templates/api/#using-requestcontext
    """

    return {
        "SenderKind": job_aplication_enums.SenderKind,
    }
