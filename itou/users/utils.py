import re

from itou.users.models import JobSeekerAssignment


# https://fr.wikipedia.org/wiki/Num%C3%A9ro_de_s%C3%A9curit%C3%A9_sociale_en_France#Signification_des_chiffres_du_NIR
NIR_RE = re.compile(
    """
    ^
    [0-9]      # sexe
    [0-9]{2}   # année de naissance
    [0-9]{2}   # mois de naissance
    [0-9]      # premier chiffre du département
    [0-9AB]  # deuxième chiffre du département
    [0-9]{3}   # lieu de naissance
    [0-9]{3}   # numéro d’ordre de naissance
    [0-9]{2}   # clé
    $""",
    re.IGNORECASE | re.VERBOSE,
)


def merge_job_seeker_assignments(*, assignment_to_delete, assignment_to_keep):
    last_assignment = max([assignment_to_delete, assignment_to_keep], key=lambda a: a.updated_at)
    JobSeekerAssignment.objects.filter(pk=assignment_to_keep.pk).update(
        created_at=min(assignment_to_delete.created_at, assignment_to_keep.created_at),
        updated_at=last_assignment.updated_at,
        last_action_kind=last_assignment.last_action_kind,
        job_seeker=assignment_to_keep.job_seeker,
    )
    assignment_to_delete.delete()
