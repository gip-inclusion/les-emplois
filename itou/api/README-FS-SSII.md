# Envoi des fiches salarié (FS) des emplois de l'inclusion vers les logiciels

Ceci est une documentation publique à destination des logiciels SSII pour la récupération de fiches salarié depuis les emplois de l'inclusion via une API dédiée.

## Principe

- Le logiciel commence par appeler l'endpoint API `api/v1/token-auth` des emplois de l'inclusion en fournissant le login/mdp de l'utilisateur employeur des emplois de l'inclusion et obtient ainsi un token qu'il pourra utiliser pour les autres endpoints.

- Le logiciel appelle ensuite l'endpoint `api/v1/employee-records` avec ce token et récupère ainsi la totalité des FS de toutes les structures de cet utilisateur et les dédoublonne si besoin en se basant sur l'unicité du couple (SIRET, PASS IAE).

- L'endpoint `api/v1/employee-records` n'est pas encore disponible mais en attendant vous pouvez déjà utiliser l'endpoint similaire `api/v1/dummy-employee-records` pour faire vos premiers tests.

- L'endpoint `api/v1/dummy-employee-records` renvoit systématiquement 25 fiches salarié sur 2 pages avec des données factices mais réalistes, peu importe le compte employeur utilisé. Si vous ne disposez pas d'un compte employeur en production, nous vous invitons à utiliser le compte employeur `test+etti@inclusion.beta.gouv.fr` (mot de passe `password`) pour faire vos tests sur la démo (https://demo.emplois.inclusion.beta.gouv.fr/) au lieu de la production (https://emplois.inclusion.beta.gouv.fr/). Merci de ne pas créer de compte factice en production.

## Points importants

- Il y a au plus une FS par couple (SIRET, PASS IAE). Autrement dit, si une même personne est recrutée pour la seconde fois (avec à chaque fois le même PASS IAE) dans la même SIAE (ou deux structures ayant le même SIRET), cela ne donnera pas lieu à une nouvelle FS.

- Les seules mesures concernées ici sont ACI, AI, EI, ETTI. Donc pas les EITI, GEIQ, EA, EATT.

## Exemples techniques complets avec curl

### Obtention d'un token

Exemple en production avec un compte employeur réel :

```
curl -H 'Accept: application/json; indent=4' -d "username=john.doe@mail.com&password=abcdef" https://emplois.inclusion.beta.gouv.fr/api/v1/token-auth/
```

Exemple en démo avec le compte de test :

```
curl -H 'Accept: application/json; indent=4' -d "username=test%2Betti@inclusion.beta.gouv.fr&password=password" https://demo.emplois.inclusion.beta.gouv.fr/api/v1/token-auth/
```

Réponse :

```
{
    "token": "123abc123abc123abc123abc123abc123abc123abc"
}
```

Notes :

- [Vous devez encoder tout caractère spécial](https://fr.wikipedia.org/wiki/Encodage-pourcent) dans l'email et le mot de passe. Par exemple `+` devient `%2B`.
- Pour les développeurs itou qui souhaitent utiliser l'API en local dev, remplacer `https://emplois.inclusion.beta.gouv.fr` par `http://localhost:8000`.


### Obtention des FS

Exemple en production avec un compte employeur réel :

```
curl -H 'Accept: application/json; indent=4' -H 'Authorization: Token 123abc123abc123abc123abc123abc123abc123abc' https://emplois.inclusion.beta.gouv.fr/api/v1/dummy-employee-records/
```

Exemple en démo avec le compte de test :

```
curl -H 'Accept: application/json; indent=4' -H 'Authorization: Token 123abc123abc123abc123abc123abc123abc123abc' https://demo.emplois.inclusion.beta.gouv.fr/api/v1/dummy-employee-records/
```

Réponse (première page présentant 20 des 25 FS) :

```
{
    "count": 25,
    "next": "https://emplois.inclusion.beta.gouv.fr/api/v1/dummy-employee-records/?page=2",
    "previous": null,
    "results": [
        # Première FS.
        {
            "mesure": "ACI_DC",
            "siret": "33055039315080",
            [...]
        },
        # Seconde FS.
        {
            "mesure": "ACI_DC",
            "siret": "33055039315080",
            [...]
        },
        [...]
    ]
}
```

Obtention de la seconde page de résultats :

```
curl -H 'Accept: application/json; indent=4' -H 'Authorization: Token 123abc123abc123abc123abc123abc123abc123abc' https://emplois.inclusion.beta.gouv.fr/api/v1/dummy-employee-records/?page=2
```

## Référentiels utiles

Tous les référentiels utiles mentionnés dans le JSON ci-dessous sont [disponibles en CSV](https://github.com/betagouv/itou/tree/vgrange/fiche_salarie/itou/fiche_salarie/management/commands/data).

## Documentation du détail d'une FS sur un exemple

```
# Exemple de FS.
# Tous les champs sont obligatoires sauf ceux mentionnés facultatifs.
{
    # Uniquement EI ETTI ACI AI. Pas EITI EA EATT GEIQ.
    "mesure": "ACI_DC",
    "siret": "33055039301440",
    # Suffixe AxMx toujours présent.
    "numeroAnnexe": "ACI023201111A0M0",
    "personnePhysique": {
        # Numéro de PASS IAE, comme un numéro d'agrément, commence
        # souvent par 99999 mais pas toujours. 12 chiffres.
        "passIae": "999992006615",
        # Toujours vide.
        "sufPassIae": null,
        # Identifiant quasi-unique du candidat sur les emplois de l'inclusion.
        # 30 caractères.
        "idItou": "70a6d71e4265a5768ad3b3f293ffd7",
        "civilite": "M",
        "nomUsage": "DECAILLOUX",
        # Facultatif.
        "nomNaissance": null,
        "prenom": "YVES",
        "dateNaissance": "01/08/1954",
        "codeComInsee": {
            # Code commune INSEE de naissance.
            # Doit faire partie de ref_insee_com_v1.csv
            "codeComInsee": "34172",
            # Code département de naissance.
            # Doit faire partie de ref_insee_dpt_v2.csv
            "codeDpt": "034"
        },
        # Doit faire partie de ref_insee_pays_v4.csv
        "codeInseePays": "100",
        # Doit faire partie de ref_grp_pays_v1.csv
        "codeGroupePays": "1"
    },
    "adresse": {
        # Facultatif.
        "adrTelephone": "0123456789",
        # Facultatif.
        "adrMail": "john.doe@gmail.com",
        # Facultatif.
        "adrNumeroVoie": "1",
        # Facultatif.
        # Doit faire partie de ref_extension_voie_v1.csv
        "codeextensionvoie": null,
        # Doit faire partie de ref_type_voie_v3.csv
        "codetypevoie": "AV",
        "adrLibelleVoie": "AVENUE ABBE PAUL PARGUEL",
        # Facultatif.
        "adrCpltDistribution": null,
        # Doit faire partie de ref_insee_com_v1.csv
        "codeinseecom": "34172",
        # référentiel inconnu - à clarifier
        "codepostalcedex": "34000"
    },
    "situationSalarie": {
        # Doit faire partie de ref_orienteur_v5.csv
        # Ce référentiel est encore incomplet, à résoudre.
        "orienteur": "01",
        # Doit faire partie de ref_niveau_formation_v3.csv
        "niveauFormation": "00",
        "salarieEnEmploi": true,
        # Doit faire partie de ref_type_employeur_v3.csv
        # Doit être rempli si et seulement si salarieEnEmploi est true.
        "salarieTypeEmployeur": "01",
        # Doit faire partie de ref_duree_allocation_emploi_v2.csv
        # Doit être rempli si et seulement si salarieEnEmploi est false.
        "salarieSansEmploiDepuis": null,
        "salarieSansRessource": false,
        "inscritPoleEmploi": true,
        # Doit faire partie de ref_duree_allocation_emploi_v2.csv
        # Doit être rempli si et seulement si inscritPoleEmploi est true.
        "inscritPoleEmploiDepuis": "01",
        # Identifiant PE du candidat.
        # Doit être rempli si et seulement si inscritPoleEmploi est true.
        "numeroIDE": "3500000A",
        "salarieRQTH": false,
        "salarieOETH": false,
        # Dixit Mélanie : Dans la même idée : ATA n'est pas demandée sur ITOU mais l'est sur l'ASP. Cette aide conditionne le true/false de l'aide sociale.
        "salarieAideSociale": false,
        # OUI-M (oui majoré), OUI-NM (oui non majoré), NON.
        "salarieBenefRSA": "NON",
        # Doit faire partie de ref_duree_allocation_emploi_v2.csv
        # Doit être rempli si et seulement si salarieBenefRSA est true
        "salarieBenefRSADepuis": null,
        "salarieBenefASS": false,
        # Doit faire partie de ref_duree_allocation_emploi_v2.csv
        # Doit être rempli si et seulement si salarieBenefASS est true
        "salarieBenefASSDepuis": null,
        "salarieBenefAAH": false,
        # Doit faire partie de ref_duree_allocation_emploi_v2.csv
        # Doit être rempli si et seulement si salarieBenefAAH est true
        "salarieBenefAAHDepuis": null,
        # L'ATA n'existe plus mais il y a encore des bénéficiaires.
        "salarieBenefATA": false,
        # Doit faire partie de ref_duree_allocation_emploi_v2.csv
        # Doit être rempli si et seulement si salarieBenefATA est true
        "salarieBenefATADepuis": null
    }
}
```




