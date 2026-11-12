import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from itou.cnav.enums import CNAVRecordOrigin
from itou.users.models import JobSeekerProfile


class CNAVRecord(models.Model):
    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    origin = models.CharField(
        choices=CNAVRecordOrigin.choices,
    )

    profile = models.ForeignKey(JobSeekerProfile, null=True, on_delete=models.SET_NULL, related_name="cnav_records")
    input_data = models.JSONField(encoder=DjangoJSONEncoder)
    result = models.JSONField(encoder=DjangoJSONEncoder)
    last_attempt_at = models.DateTimeField()


# TODO:
# Ajout d'une tache huey qui prend la pk de ce modèle en entrée et qui (en prenant un lock):
#   * vérifie si il n'y a pas déjà un résultat (potentiellement vide)
#   * si c'est le cas: rien à faire et on quitte
#   * sinon:
#     - on interroge l'API de la CNAV:
#         * si soucis de communication, on met juste à jour last_attempt_at et on quitte en remettant une tache huey
#           à plus tard (raise RetryTask(delay=xxx)). Pour les 429, bien lire l'header pour suffisamment repousser
#         * si réponse de l'API:
#           - on stocke last_attempt_at et le résultat
#           - si le résultat est négatif, on recrée un autre objet avec dans input data une liste de champs plus
#             réduite pour réinterroger la CNAV (il faudra vérifier si cela est pertinent)
#
# Ajout d'une tache planifiée qui supprime les vieux objets non liés à un profile
# Ajout d'une tache planifiée qui tente de traiter les vieilles taches huey
# Modification de la fusion de deux comptes candidats pour garder ces objets
#
# Lors de la création d'un compte candidat: on crée cet objet dès que toutes les informations sont récupérées,
# on stocke la pk de cet objet dans la session et on enqueue la tache on_commit.
# A la dernière étape, si l'usager est bien créé, on rattache l'objet à l'usager (quelque soit le résultat de l'appel
# à la CNAV.
# Si:
#   - le pro a le droit de voir les infos de la CNAV
#   - la CNAV a déjà répondu à notre appel
#   - les informations ne correspondent pas exactement
# alors on affiche le tableau comparatif (à quelle étape ?) pour laisser le pro choisir quelles données qu'il
# souhaite conserver
# S'il choisit la CNAV (ou si les données correspondaient parfaitement), on rajoute sur le profile une FK cnav_infos
# qui pointe vers l'objet des données récupérées, ou alors un IdentityCertificationAuthorities
# La présence de cette clef indique que le profil de l'usager est certifié et il ne peut plus changer
# - son nom de naissance
# - son prénom (ou uniquement le changer pour un de ses prénoms ?)
# - sa date de naissance
# - son lieu de naissance
# - son sexe
