# Envoi des fiches salarié (FS) de la plateforme vers les logiciels

## Principe

Le logiciel se connecte à un endpoint API dédié de la plateforme (à venir) en fournissant le login/mdp de l'utilisateur employeur de la plateforme.

Le logiciel récupère ainsi la totalité des FS de toutes les structures de cet utilisateur et dédoublonne en se basant sur l'unicité du couple (SIRET, PassIAE).

Oauth2 : https://developer.aife.economie.gouv.fr/

## Points importants

- il y a au plus une FS par couple (SIRET, PassIAE). Autrement dit si une personne est recrutée pour la seconde fois dans la même SIAE, cela ne donnera pas lieu à une nouvelle FS.
- les seules mesures concernées ici sont ACI, EI et ETTI. Donc pas les AI ni les EITI.

## Référentiels utiles

Tous les référentiels utiles mentionnés dans le JSON ci-dessous sont disponibles en CSV [ici](https://github.com/betagouv/itou/tree/vgrange/fiche_salarie/itou/fiche_salarie/management/commands/data).

## Exemple et documentation du JSON d'une FS


```
[
    # Première FS.
    # Tous les champs sont obligatoires sauf ceux mentionnés facultatifs.
    {
        # Uniquement EI EITI ACI. Pas AI ni EITI.
        "mesure": "ACI_DC",
        "siret": "33055039301440",
        # Question : suffixe complet (A0M0) partiel (A0) ou pas de suffixe?
        # Réponse (Maréchal) : besoin du suffixe complet A0M0.
        "numeroAnnexe": "ACI023201111A0",
        "personnePhysique": {
            # Numéro de PASS IAE, comme un numéro d'agrément, commence
            # souvent par 99999 mais pas toujours. 12 chiffres.
            "passIae": "999992006615",
            # Toujours vide.
            "sufPassIae": null,
            # Identifiant quasi-unique du candidat sur la plateforme.
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
            # Doit faire partie de ref_orienteur_v4.csv
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
    },
    # Seconde FS
    {
        "mesure": "EI_DC",
        "siret": "33055039301440",
        "numeroAnnexe": "ACI023201111A0",
        "personnePhysique": {
            # ...
        },
        "adresse": {
            # ...
        },
        "situationSalarie": {
            # ...
        }
    }
]
```