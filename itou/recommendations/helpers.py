import dataclasses
import datetime
import logging

from django.core.cache import cache

from itou.utils.apis.pole_emploi import Apps, pole_emploi_agent_api_client


logger = logging.getLogger(__name__)


CACHE_DURATION = 60 * 60  # 1 hour


def get_user_data(ft_id):
    cache_key = f"RECOMMENDATIONS_DATA_{ft_id}"
    if user_data := cache.get(cache_key):
        return user_data
    try:
        user_data = fetch_and_parse_user_data(ft_id)
        cache.set(cache_key, user_data, timeout=CACHE_DURATION)
        return user_data
    except Exception:
        # We probably had an httpx.HttpError when calling the api
        # or a KeyError when parsing the data
        # log the error for now
        logger.exception("Unable to fetch and parse user data")
        return None


@dataclasses.dataclass
class Address:
    address_line_1: str
    address_line_2: str
    post_code: str
    city: str
    insee_code: str

    @property
    def on_one_line(self):
        if not all([self.address_line_1, self.post_code, self.city]):
            return None
        fields = [
            self.address_line_1,
            self.address_line_2,
            f"{self.post_code} {self.city}",
        ]
        return ", ".join([field for field in fields if field])


@dataclasses.dataclass
class AdministrativeData:
    title: str
    first_name: str
    last_name: str
    birthdate: datetime.date
    phone: str = ""
    email: str = ""
    address: Address | None = None
    is_in_qpv: bool = False
    # TODO: Add in_zrr / partially_in_zrr


@dataclasses.dataclass
class Status:
    """Data structure user status in FT : for how long he is registered"""

    registered: bool
    since: datetime.date
    deld: bool
    detld: bool


@dataclasses.dataclass
class Criterion:
    brsa: bool
    boe: bool
    level_of_education: str
    # see api documentation for values for level_of_education
    # we might need a smart enum to sort them so that we can ask for a
    # level lower than X
    # AFS	Aucune formation scolaire
    # CP4	Primaire à 4ème
    # CFG	4ème achevée
    # C3A	3ème achevée ou Brevet
    # C12	2nd ou 1ère achevée
    # NV5	CAP, BEP et équivalents
    # NV4	Bac ou équivalent
    # NV3	Bac+2 ou équivalents
    # NV2	Bac+3, Bac+4 ou équivalents
    # NV1	Bac+5 et plus ou équivalents
    currently_employed: bool


@dataclasses.dataclass
class Author:
    """Data structure for diagnosis authors with timestamp"""

    first_name: str
    last_name: str
    organization: str
    timestamp: datetime.datetime | None

    @classmethod
    def from_agent(cls, agent, timestamp):
        return cls(
            first_name=agent["prenom"],
            last_name=agent["nom"],
            organization=agent["structure"],
            timestamp=datetime.datetime.fromisoformat(timestamp) if timestamp else None,
        )


@dataclasses.dataclass
class CapacityToAct:
    """Data structure for "pouvoirAgir" objects from Diagnostic Usager - dossier agrégé"""

    label: str
    author: Author


@dataclasses.dataclass
class Need:
    """Data structure for "besoin" objects from Diagnostic Usager - dossier agrégé"""

    label: str
    value: str
    author: Author

    @classmethod
    def from_dict(cls, data):
        return cls(
            label=data["libelle"],
            value=data["valeur"],
            author=Author.from_agent(data["agent"], data["dateExploration"]),
        )


@dataclasses.dataclass
class Constraint:
    """Data structure for "contrainte" objects from Diagnostic Usager - dossier agrégé"""

    # NB: Each item in details is a "objectif" or a "situation" from the API.
    # These have their own author, value, and impact
    # but we chose not to use them for now (too much information to display)

    code: str
    label: str
    details: list[str]
    author: Author
    impact: str
    high_priority: bool

    @classmethod
    def from_dict(cls, agent, data):
        return cls(
            code=data["code"],
            label=data["libelle"],
            impact=data.get("impact", ""),  # This field is missing in one of the examples from the doc.
            details=[o["libelle"] for o in data["objectifs"] + data["situations"]],
            author=Author.from_agent(agent, data["dateExploration"]),
            high_priority=data["estPrioritaire"],
        )


@dataclasses.dataclass
class Diagnosis:
    """Data structure for the user "besoinsParDiagnostic" from Diagnostic Usager - dossier agrégé"""

    name: str
    author: Author
    high_priority: bool
    needs: list[Need]


@dataclasses.dataclass
class ConsolidatedFile:
    """Data structure for the user consolidated file data from Diagnostic Usager - dossier agrégé"""

    capacity_to_act: CapacityToAct
    digital_autonomy_need: Need
    digital_autonomy_constraint: Constraint
    constraints: list[Constraint]
    diagnoses: list[Diagnosis]


@dataclasses.dataclass
class UserData:
    """Data structure for the user complete parsed data"""

    administrative_data: AdministrativeData
    status: Status
    criteria: Criterion
    consolidated_file: ConsolidatedFile


def fetch_and_parse_user_data(ft_id):
    with pole_emploi_agent_api_client(app=Apps.SPS) as pe_client:
        token = pe_client.rechercher_usager(france_travail_id=ft_id)

        # Fetch administrative data
        raw_administrative_data = pe_client.informations_administratives_usager(token)
        if not raw_administrative_data:
            raise ValueError(f"Missing administrative data for id={ft_id}")
        administrative_data = AdministrativeData(
            first_name=raw_administrative_data["etatCivil"]["prenom"],
            last_name=raw_administrative_data["etatCivil"]["nom"],
            birthdate=datetime.date.fromisoformat(raw_administrative_data["etatCivil"]["dateNaissance"]),
            title=raw_administrative_data["etatCivil"]["civilite"],
        )
        if phones := raw_administrative_data["telephones"]:
            administrative_data.phone = phones[0]["numeroTelephone"]
        if emails := raw_administrative_data["emails"]:
            administrative_data.email = emails[0]["adresseEmail"]
        if addresses := raw_administrative_data["adresses"]:
            administrative_data.address = Address(
                address_line_1=addresses[0]["numeroTypeLibelleVoie"],
                address_line_2=addresses[0]["complementAdresse"],
                post_code=addresses[0]["codePostal"],
                city=addresses[0]["libelleCommune"],
                insee_code=addresses[0]["codeInseeCommune"],
            )
            if addresses[0]["indicateurResidentQPV"] == "QP":
                administrative_data.is_in_qpv = True

        # Fetch FT status
        raw_status = pe_client.statut_usager(token)
        if not raw_status:
            raise ValueError(f"Missing user status data for id={ft_id}")
        status = Status(
            registered=raw_status["m_contrat"]["m_statut"] == "Inscrit",
            since=datetime.date.fromisoformat(raw_status["m_contrat"]["m_date_effet_statut"]),
            deld=raw_status["m_contrat"]["m_duree_inscription_12"] == 12,
            detld=raw_status["m_contrat"]["m_duree_inscription_24"] == 24,
        )

        # Fetch user guidance
        raw_criteria = pe_client.orientation_usager(token)
        criteria = None
        if raw_criteria:
            criteria = Criterion(
                brsa=raw_criteria[0]["criteres_orientation"]["brsa"],
                boe=raw_criteria[0]["criteres_orientation"]["boe"],
                level_of_education=raw_criteria[0]["criteres_orientation"]["niveau_etude"],
                currently_employed=raw_criteria[0]["criteres_orientation"]["situation_professionnelle"]
                == "EN_ACTIVITE",
            )

        # Fetch user diagnosis
        raw_consolidated_file = pe_client.diagnostic_usager_dossier_agrege(token)
        if not raw_consolidated_file:
            raise ValueError(f"Missing consolidated file for id={ft_id}")
        capacity_to_act = CapacityToAct(
            label=raw_consolidated_file["pouvoirAgir"]["resultatAnalyse"],
            author=Author.from_agent(
                agent=raw_consolidated_file["pouvoirAgir"]["agent"],
                timestamp=raw_consolidated_file["pouvoirAgir"]["dateExploration"],
            ),
        )
        digital_autonomy_need = Need.from_dict(data=raw_consolidated_file["autonomieNumerique"]["besoin"])
        digital_autonomy_constraint = Constraint.from_dict(
            agent=raw_consolidated_file["autonomieNumerique"]["agent"],
            data=raw_consolidated_file["autonomieNumerique"]["contrainte"],
        )
        constraints = []
        for raw_constraint in raw_consolidated_file["thematiqueContrainte"]["contraintes"]:
            if raw_constraint["valeur"] == "OUI":
                constraints.append(
                    Constraint.from_dict(
                        agent=raw_consolidated_file["thematiqueContrainte"]["agent"],
                        data=raw_constraint,
                    )
                )
        diagnoses = []
        for raw_diagnosis in raw_consolidated_file["besoinsParDiagnostic"]:
            if raw_diagnosis["diagnostic"]["statut"] == "EN_COURS":
                needs = [
                    Need.from_dict(data=raw_need)
                    for raw_needs in raw_diagnosis["thematiquesBesoins"]
                    for raw_need in raw_needs["besoins"]
                    if raw_need["valeur"] != "NON_EXPLORE"
                ]
                diagnoses.append(
                    Diagnosis(
                        author=Author.from_agent(
                            agent=raw_diagnosis["diagnostic"]["agent"],
                            timestamp=raw_diagnosis["diagnostic"]["dateMiseAJour"],
                        ),
                        name=raw_diagnosis["diagnostic"]["nomMetier"],
                        high_priority=raw_diagnosis["diagnostic"]["estPrioritaire"],
                        needs=needs,
                    )
                )

        consolidated_file = ConsolidatedFile(
            capacity_to_act=capacity_to_act,
            digital_autonomy_need=digital_autonomy_need,
            digital_autonomy_constraint=digital_autonomy_constraint,
            constraints=constraints,
            diagnoses=diagnoses,
        )

    # Regroup everything
    return UserData(
        administrative_data=administrative_data,
        status=status,
        criteria=criteria,
        consolidated_file=consolidated_file,
    )
