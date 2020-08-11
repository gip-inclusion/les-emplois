from django.conf import settings
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext

from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS


def convert_boolean_to_int(b):
    # True => 1, False => 0, None => None.
    return None if b is None else int(b)


def compose(f, g):
    # Compose two lambda methods.
    # https://stackoverflow.com/questions/16739290/composing-functions-in-python
    # I had to use this to solve a cryptic
    # `RecursionError: maximum recursion depth exceeded` error
    # when composing convert_boolean_to_int and c["lambda"].
    return lambda *a, **kw: f(g(*a, **kw))


def get_choice(choices, key):
    choices = dict(choices)
    # Gettext fixes `can't adapt type '__proxy__'` error
    # due to laxy_gettext and psycopg2 not going well together.
    # See https://code.djangoproject.com/ticket/13965
    if key in choices:
        return gettext(choices[key])
    return None


def chunks(items, n):
    """
    Yield successive n-sized chunks from items.
    """
    for i in range(0, len(items), n):
        yield items[i : i + n]


def anonymize(value, salt):
    """
    Use a salted hash to anonymize sensitive ids,
    mainly job_seeker id and job_application id.
    """
    return salted_hmac(salt, value, secret=settings.SECRET_KEY).hexdigest()


def get_first_membership_join_date(memberships):
    memberships = list(memberships.all())
    # We have to do all this in python to benefit from prefetch_related.
    if len(memberships) >= 1:
        memberships.sort(key=lambda o: o.joined_at)
        first_membership = memberships[0]
        return first_membership.joined_at
    return None


def _get_job_seeker_id_to_hiring_siae():
    """
    Ideally the job_seeker would have a unique hiring so that we can
    properly link the approval back to the siae. However we already
    have many job_seekers with two or more hirings. In this case
    we consider the latest hiring, which is an ugly workaround
    around the issue that we do not have a proper approval=>siae
    link yet.

    Preload this association data for best performance.
    """
    # Order by created_at so that most recent hiring overrides older ones.
    hirings = (
        JobApplication.objects.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)
        .order_by("created_at")
        .select_related("to_siae")
    )
    job_seeker_id_to_hiring_siae = {}
    for hiring in hirings:
        job_seeker_id = hiring.job_seeker_id
        job_seeker_id_to_hiring_siae[job_seeker_id] = hiring.to_siae
    return job_seeker_id_to_hiring_siae


JOB_SEEKER_ID_TO_HIRING_SIAE = _get_job_seeker_id_to_hiring_siae()


def get_department_and_region_columns(name_suffix="", comment_suffix="", custom_lambda=lambda o: o):
    return [
        {
            "name": f"département{name_suffix}",
            "type": "varchar",
            "comment": f"Département{comment_suffix}",
            "lambda": lambda o: getattr(custom_lambda(o), "department", None),
        },
        {
            "name": f"nom_département{name_suffix}",
            "type": "varchar",
            "comment": f"Nom complet du département{comment_suffix}",
            "lambda": lambda o: DEPARTMENTS.get(getattr(custom_lambda(o), "department", None)),
        },
        {
            "name": f"région{name_suffix}",
            "type": "varchar",
            "comment": f"Région{comment_suffix}",
            "lambda": lambda o: DEPARTMENT_TO_REGION.get(getattr(custom_lambda(o), "department", None)),
        },
    ]


def get_address_columns(name_suffix="", comment_suffix=""):
    return [
        {
            "name": f"adresse_ligne_1{name_suffix}",
            "type": "varchar",
            "comment": f"Première ligne adresse{comment_suffix}",
            "lambda": lambda o: o.address_line_1,
        },
        {
            "name": f"adresse_ligne_2{name_suffix}",
            "type": "varchar",
            "comment": f"Seconde ligne adresse{comment_suffix}",
            "lambda": lambda o: o.address_line_2,
        },
        {
            "name": f"code_postal{name_suffix}",
            "type": "varchar",
            "comment": f"Code postal{comment_suffix}",
            "lambda": lambda o: o.post_code,
        },
        {
            "name": f"ville{name_suffix}",
            "type": "varchar",
            "comment": f"Ville{comment_suffix}",
            "lambda": lambda o: o.city,
        },
    ] + get_department_and_region_columns(name_suffix, comment_suffix)
