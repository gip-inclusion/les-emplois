from django import template

from itou.job_applications.enums import JobApplicationState, Origin, RefusalReason, SenderKind


register = template.Library()


@register.simple_tag()
def job_applications_enums():
    return {
        "JobApplicationState": JobApplicationState,
        "Origin": Origin,
        "RefusalReason": RefusalReason,
        "SenderKind": SenderKind,
    }
