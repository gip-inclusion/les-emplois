from datetime import date, timedelta
from random import choice
from time import sleep

from django.core.management.base import BaseCommand
from httpx import HTTPStatusError

from itou.job_applications.models import JobApplication
from itou.siaes.models import Siae
from itou.utils.apis.esd import get_access_token
from itou.utils.apis.pole_emploi import (
    PoleEmploiIndividu,
    PoleEmploiMiseAJourPass,
    PoleEmploiMiseAJourPassIAEAPI,
    PoleEmploiRechercheIndividuCertifieAPI,
)


class SamplePoleEmploiUsers:
    def demandeur_ok():
        # With these users, there should be no error in particular
        return choice(
            [
                PoleEmploiIndividu("CELINE", "HUBERT", date(1975, 5, 23), "2750533063506"),
                PoleEmploiIndividu("VERONIQUE", "CANTELAUBE", date(1973, 6, 30), "2730624520042"),
                PoleEmploiIndividu("CATHERINE", "ROUSSARIE", date(1955, 11, 20), "2551124322076"),
                PoleEmploiIndividu("LANDRY", "HERMANOWIEZ", date(1968, 10, 23), "1681040192074"),
                PoleEmploiIndividu("FREDERIC", "MAURY", date(1961, 1, 23), "1610133402024"),
                PoleEmploiIndividu("LAURENT", "WICHEGROD", date(1962, 3, 4), "1620378172012"),
                PoleEmploiIndividu("CATHERINE", "WISSOCQ", date(1971, 5, 18), "2710524520029"),
                PoleEmploiIndividu("YOLANDE", "BARANES", date(1957, 4, 19), "2570499351058"),
                PoleEmploiIndividu("BRIGITTE", "LATREILLE", date(1959, 11, 17), "2591119031056"),
                PoleEmploiIndividu("COLETTE", "BEAUVIEUX", date(1959, 4, 1), "2590424082001"),
                PoleEmploiIndividu("AGNES", "GEOFFROY", date(1959, 5, 18), "2590542218236"),
                PoleEmploiIndividu("BRIGITTE", "BONNEFOND", date(1959, 3, 19), "2590347323167"),
                PoleEmploiIndividu("ROGER", "COZE", date(1960, 2, 7), "1600283137052"),
                PoleEmploiIndividu("ERIC", "SDEI", date(1960, 12, 26), "1601203190078"),
                PoleEmploiIndividu("JACKY", "LAPOUGES", date(1960, 7, 30), "1600724199003"),
                PoleEmploiIndividu("PATRICIA", "BEN KENZA", date(1960, 3, 20), "2600315138006"),
                PoleEmploiIndividu("THIERRY", "CASTAGNOL", date(1961, 4, 14), "1610424142003"),
                PoleEmploiIndividu("SYLVIE", "LATREILLE", date(1962, 11, 3), "2621124172001"),
                PoleEmploiIndividu("PASCAL", "PLANET", date(1962, 3, 6), "1620319275055"),
                PoleEmploiIndividu("BRIGITTE", "SDEI", date(1962, 10, 21), "2621024291020"),
                PoleEmploiIndividu("JEAN-MICHEL", "LACOUTURE", date(1964, 10, 5), "1641024068005"),
                PoleEmploiIndividu("ESPERANCA", "DOS SANTOS", date(1964, 3, 1), "2640399139680"),
                PoleEmploiIndividu("MARIA", "VERISSIMO", date(1964, 4, 3), "2640499139829"),
                PoleEmploiIndividu("CHRISTINE", "RIBOULOT", date(1964, 2, 11), "2640271014077"),
                PoleEmploiIndividu("PHILIPPE", "FAVIER", date(1966, 7, 29), "1660736006209"),
                PoleEmploiIndividu("OLIVIER", "GARRIGOU", date(1966, 1, 20), "1660124035013"),
                PoleEmploiIndividu("JOSE", "CARROLA DOS REIS", date(1966, 7, 19), "1660799139531"),
                PoleEmploiIndividu("PASCALE", "UGONI", date(1966, 10, 6), "2661033243030"),
                PoleEmploiIndividu("SANDRINE", "DELMAS", date(1967, 12, 19), "2671275114525"),
                PoleEmploiIndividu("VERONIQUE", "ROQUE", date(1968, 4, 12), "2680424520096"),
                PoleEmploiIndividu("JEROME", "NOUHAUD", date(1969, 6, 10), "1690624037027"),
                PoleEmploiIndividu("CATHERINE", "AFONSO", date(1969, 4, 12), "2690424520132"),
                PoleEmploiIndividu("MONIQUE", "CARAMEL", date(1969, 10, 3), "2691024520337"),
                PoleEmploiIndividu("VALERIE", "VAUDOIS", date(1969, 11, 15), "2691124322066"),
                PoleEmploiIndividu("PAULA", "CARVALHO", date(1969, 12, 9), "2691299139208"),
            ]
        )

    # These users have errors that range from S008 to S017
    def demandeur_s008():
        # Individu radié
        return choice(
            [
                PoleEmploiIndividu("PIERRE", "BARBIER", date(1978, 6, 14), "1780633243064"),
                PoleEmploiIndividu("JACQUES", "DUPUY", date(1958, 3, 25), "1580376552150"),
                PoleEmploiIndividu("JEROME", "MARTIN", date(1973, 8, 10), "1730890010076"),
            ]
        )

    def demandeur_s013():
        # Individu sans référent de suivi principal
        return choice(
            [
                PoleEmploiIndividu("CHRISTEL", "TASTE", date(1974, 11, 21), "2741133039040"),
                PoleEmploiIndividu("THOMAS", "DUBOIS", date(1976, 11, 25), "1761133063442"),
                PoleEmploiIndividu("ELODIE", "DAMOUR", date(1991, 4, 19), "2910402691386"),
            ]
        )

    def demandeur_s015():
        # Individu avec suivi délégué déjà en cours
        return choice(
            [
                # Rouche renvoie un code S100 et non S015
                # PoleEmploiIndividu("CYRIL", "ROUCHE", date(1998, 11, 10), "1981175120558"),
                PoleEmploiIndividu("XAVIER", "ROUQUIER", date(1986, 10, 27), "1861093050031"),
            ]
        )

    def demandeur_s017():
        # Individu en suivi CRP (donc non EDS)
        return choice(
            [
                PoleEmploiIndividu("MARIE", "HUBERT", date(1970, 4, 18), "2700424037062"),
                PoleEmploiIndividu("MYRIAM", "CARTON", date(1971, 2, 1), "2710299140039"),
            ]
        )

    # These users have errors that range from S032 to S043
    def demandeur_s032():
        return choice(
            [
                PoleEmploiIndividu("JEAN", "BEAUZETIE", date(1954, 7, 1), "1540724304005"),
                PoleEmploiIndividu("ALAIN", "GOYAT", date(1962, 3, 30), "1620316015156"),
            ]
        )

    def demandeur_s036():
        return choice(
            [
                PoleEmploiIndividu("WILLY", "GIRY", date(1967, 12, 14), "1671224322077"),
                PoleEmploiIndividu("JEAN", "LAPOUGE", date(1954, 11, 21), "1541199350543"),
            ]
        )


class Command(BaseCommand):
    """
    Performs a sample HTTP request to pole emploi

    When ready:
        django-admin fetch_pole_emploi --verbosity=2
    """

    help = "Test synchronizing sample user data stored by Pole Emploi"

    # The following sample users are provided by Pole Emploi.
    # Dependending on their category, we know what kind of error the API should provide.

    API_DATE_FORMAT = "%Y-%m-%d"

    def generate_sample_api_params(self, encrypted_identifier):
        approval_start_at = date(2021, 6, 1)
        approval_end_at = date(2021, 7, 1)
        approved_pass = "A"
        approval_number = "999992139048"
        siae_siret = "42373532300044"

        return {
            "idNational": encrypted_identifier,
            "statutReponsePassIAE": approved_pass,
            "typeSIAE": PoleEmploiMiseAJourPass.kind(Siae.KIND_EI),
            "dateDebutPassIAE": approval_start_at.strftime(self.API_DATE_FORMAT),
            "dateFinPassIAE": approval_end_at.strftime(self.API_DATE_FORMAT),
            "numPassIAE": approval_number,
            "numSIRETsiae": siae_siret,
            "origineCandidature": PoleEmploiMiseAJourPass.sender_kind(JobApplication.SENDER_KIND_JOB_SEEKER),
        }

    def is_dry_run(self, api_production_or_sandbox):
        return api_production_or_sandbox == PoleEmploiMiseAJourPassIAEAPI.USE_SANDBOX_ROUTE

    def get_token(self, api_production_or_sandbox):
        print("demande de token rechercherIndividuCertifie et MiseAJourPass")
        try:
            maj_pass_iae_api_scope = "passIAE api_maj-pass-iaev1"
            if self.is_dry_run(maj_pass_iae_api_scope):
                maj_pass_iae_api_scope = "passIAE api_testmaj-pass-iaev1"

            # It is not obvious but we can ask for one token only with all the necessary rights
            token_recherche_et_maj = get_access_token(
                f"api_rechercheindividucertifiev1 rechercherIndividuCertifie {maj_pass_iae_api_scope}"
            )
            sleep(1)
            return token_recherche_et_maj
        except HTTPStatusError as error:
            print(error.response.content)

    def get_pole_emploi_individual(self, individual, api_token):
        # print("rechercherIndividuCertifie")
        # print(individual.as_api_params())
        try:
            individual_pole_emploi = PoleEmploiRechercheIndividuCertifieAPI(individual, api_token)
            # 3 requests/second max. I had timeout issues so 1 second take some margins
            sleep(1)  #
            if not individual.is_valid:
                print(f"Error while fetching individual: {individual.code_sortie}")

            return individual_pole_emploi
        except HTTPStatusError as error:
            print(error.response.content)

    def synchronize_pass_iae(self):
        api_mode = PoleEmploiMiseAJourPassIAEAPI.USE_PRODUCTION_ROUTE
        token_recherche_et_maj = self.get_token(api_mode)

        # Test de l’API "Mise à jour PassIAE":
        # On part d’un appel API avec des données valides, et on modifie cet appel pour tester
        # qu’on obtient bien les code sortie documentés

        test_cases = [
            # # Cas nominal
            # [SamplePoleEmploiUsers.demandeur_ok(), None, "S100"],  # si on fourni un appel valide: tout est bon
            # 1) Tests des contrôles sur les données génériques de traitement (codes erreur S001 à S003)
            # identifiant pole emploi non renseigné, ce test échoue, que je mette un idNational vide ("")
            # ou que ne fournisse pas cette valeur dans la payload. PE indique que c’est chez eux
            # ({"codeError":"E_ERR_EX042_PROBLEME_DECHIFFREMEMENT"}).
            # [SamplePoleEmploiUsers.demandeur_ok(), [["idNational", ""]], "S001"],
            # S002/S003: code traitement non renseigné. … mais on a pas de code traitement à fournir à l’API ?
            # 2) Tests des contrôles sur les données de l'individu (codes erreur S004 à S017)
            # S004 à S007: scénarios non fournis
            # S008 à S017: voir les jeux de tests qui associent un utilisateur particulier à un code erreur
            [SamplePoleEmploiUsers.demandeur_s008(), None, "S008"],  # Individu radié
            [SamplePoleEmploiUsers.demandeur_s013(), None, "S013"],  # Individu sans référent de suivi principal
            [SamplePoleEmploiUsers.demandeur_s015(), None, "S015"],  # Individu avec suivi délégué déjà en cours
            [SamplePoleEmploiUsers.demandeur_s017(), None, "S017"],  # Individu en suivi CRP
            # 3) Tests des contrôles sur les données IAE (codes erreur S018 à S031)
            [SamplePoleEmploiUsers.demandeur_ok(), [["typeSIAE", ""]], "S018"],  # SIAE non renseignée
            [SamplePoleEmploiUsers.demandeur_ok(), [["typeSIAE", "42"]], "S019"],  # SIAE différent de 836 à 840
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["statutReponsePassIAE", ""]],
                "S020",
            ],  # statut reponse pass IAE non renseigné
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["statutReponsePassIAE", "Z"]],
                "S021",
            ],  # statut reponse pass IAE différent de A ou R
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["statutReponsePassIAE", "R"]],
                "S022",
            ],  # statut reponse pass IAE = refusé
            # date de début du pass non renseignée alors que pass accepté.
            # Il faut enlever cette propriété pour rentrer dans cette configuration
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["statutReponsePassIAE", "A"], ["dateDebutPassIAE", None]],
                "S023",
            ],
            # date de début du pass dans le futur alors que pass accepté
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [
                    ["statutReponsePassIAE", "A"],
                    ["dateDebutPassIAE", (date.today() + timedelta(days=1)).strftime(self.API_DATE_FORMAT)],
                ],
                "S024",
            ],
            # date de fin du pass non renseignée alors que pass accepté.
            # Il faut enlever cette propriété pour rentrer dans cette configuration
            [SamplePoleEmploiUsers.demandeur_ok(), [["statutReponsePassIAE", "A"], ["dateFinPassIAE", None]], "S025"],
            # date de fin du pass avant la date de début
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["statutReponsePassIAE", "A"], ["dateFinPassIAE", (date(2021, 4, 1)).strftime(self.API_DATE_FORMAT)]],
                "S026",
            ],
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["numPassIAE", ""]],
                "S027",
            ],  # numero pass IAE non renseigné (cette fois-ci, mettre une chaine vide est OK.)
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["origineCandidature", ""]],
                "S028",
            ],  # origine candidature non renseignée
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["origineCandidature", "PLOP"]],
                "S029",
            ],  # origine candidature différent de ‘DEMA’, ‘PRES’ ou ‘EMPL’. Génère une 500 si on met plus de 4 lettres
            # cas S030 non spécifié
            [
                SamplePoleEmploiUsers.demandeur_ok(),
                [["numSIRETsiae", ""]],
                "S031",
            ],  # siret SIAE non renseigné alors que candidature acceptée
            # # 4) Tests des contrôles sur les données du suivi délégué PNI ITOU (codes erreur S032 à S043)
            [
                SamplePoleEmploiUsers.demandeur_s032(),
                [["typeSIAE", "840"]],
                "S032",
            ],  # Organisme ou structure inexistant dans le référentiel Partenaire
            [
                SamplePoleEmploiUsers.demandeur_s036(),
                [["typeSIAE", "839"]],
                "S036",
            ],  # Lien inexistant entre structure et organisme
        ]

        for test_case in test_cases:
            (individual, updates_to_perform, expected_code_sortie) = test_case
            print(expected_code_sortie)

            individual_pole_emploi = self.get_pole_emploi_individual(individual, token_recherche_et_maj)
            if individual_pole_emploi.is_valid:
                params = self.generate_sample_api_params(individual_pole_emploi.id_national_demandeur)
                if updates_to_perform is not None:
                    for update in updates_to_perform:
                        field_to_update, field_value = update

                        if field_value is None:
                            del params[field_to_update]
                        else:
                            params[field_to_update] = field_value

                try:
                    maj = PoleEmploiMiseAJourPassIAEAPI(params, token_recherche_et_maj, api_mode)
                    # 1 request/second max, taking a bit of margin here due to occasionnal timeouts
                    sleep(1.5)

                except HTTPStatusError as error:
                    print(error.response.content)
                if maj.code_sortie != expected_code_sortie:
                    print("unexpected result for", test_case)
                    print(individual.last_name)
                    print(maj.data)
        print()

    def handle(self, dry_run=False, **options):
        self.synchronize_pass_iae()
