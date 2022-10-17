/*

L'objectif est de créer une table qui contient des informations à l'échelle locale (bassin d'emploi, epci, etc)

*/

with candidatures_p as (
    select
        *
    from
        candidatures
),
org_prescripteur as ( /* On récupère l'id et le dept des organismes prescripteurs afin de filtrer selon le département de l'agence PE associée */
	select
		org.id as id_org,
		org.nom_département as dept_org,  /*bien mettre nom département et pas département */
		org.région as région_org 
	from
		organisations org
),
bassin_emploi as ( /* On récupère les infos locales à partir des données infra départementales */
    select
        be.libelle_commune as ville,
        be.type_epci,
        be.nom_departement,
        be.nom_region,
        be.nom_epci,
        be.code_commune,
        be.nom_arrondissement,
        be.nom_zone_emploi_2020 as bassin_d_emploi, /* zone d'emploi = bassin d'emploi */
        s.id as id_structure /* on récupère que l'id des structures de la table structure */
    from sa_zones_infradepartementales be
        left join structures s
            on s.ville = be.libelle_commune and s.nom_département = be.nom_departement /* il faut rajouter le département car la France n'est pas originale en terme de noms de ville */
),
/*On créé une colonne par réseau au cas ou une même structure appartienne à différents réseaux */
adherents_coorace as (
    select
        distinct (ria."SIRET") as siret,
        ria."Réseau IAE" as reseau_coorace,
        s.id as id_structure
    from reseau_iae_adherents ria
        inner join structures s
            on s.siret = ria."SIRET"
    where ria."Réseau IAE" = 'Coorace'
),
adherents_fei as (
    select
        distinct (ria."SIRET") as siret,
        ria."Réseau IAE" as reseau_fei,
        s.id as id_structure
    from reseau_iae_adherents ria
        inner join structures s
            on s.siret = ria."SIRET"
    where ria."Réseau IAE" = 'FEI'
),
adherents_emmaus as (
    select
        distinct (ria."SIRET") as siret,
        ria."Réseau IAE" as reseau_emmaus,
        s.id as id_structure
    from reseau_iae_adherents ria
        inner join structures s
            on s.siret = ria."SIRET"
    where ria."Réseau IAE" = 'Emmaus'
)
select
    date_candidature,
    date_embauche,
    délai_de_réponse,
    extract (DAY FROM délai_de_réponse) as temps_de_reponse,
    délai_prise_en_compte,
    candidatures_p.département_structure,
    état,
    id_anonymisé,
    id_candidat_anonymisé,
    candidatures_p.id_structure,
    motif_de_refus,
    candidatures_p.nom_département_structure,
    nom_structure,
    type_structure,
    origine,
    origine_détaillée,
    case /* Ajout colonne avec des noms de prescripteurs correspondant à ceux de la table taux_transformation_prescripteurs */
        when candidatures_p.origine_détaillée = 'Prescripteur habilité AFPA' then 'AFPA - Agence nationale pour la formation professionnelle des adultes'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité ASE' then 'ASE - Aide sociale à l''enfance'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité Autre' then 'Autre'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CAARUD' then 'CAARUD - Centre d''accueil et d''accompagnement à la réduction de risques pour usagers de drogues'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CADA' then 'CADA - Centre d''accueil de demandeurs d''asile'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CAF' then 'CAF - Caisse d''allocations familiales'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CAP_EMPLOI' then 'CAP emploi'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CAVA' then 'ACAVA - Centre d''adaptation à la vie active'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CCAS' then 'CCAS - Centre communal d''action sociale ou centre intercommunal d''action sociale'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CHRS' then 'CHRS - Centre d''hébergement et de réinsertion sociale'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CHU' then 'CHU - Centre d''hébergement d''urgence'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CIDFF' then 'CIDFF - Centre d''information sur les droits des femmes et des familles'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CPH' then 'CPH - Centre provisoire d''hébergement'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité CSAPA' then 'CSAPA - Centre de soins, d''accompagnement et de prévention en addictologie'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité DEPT' then 'Service social du conseil départemental'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité E2C' then 'E2C - École de la deuxième chance'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité EPIDE' then 'EPIDE - Établissement pour l''insertion dans l''emploi'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité HUDA' then 'HUDA - Hébergement d''urgence pour demandeurs d''asile'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité ML' then 'Mission Locale'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité MSA' then 'MSA - Mutualité Sociale Agricole'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité OACAS' then 'OACAS - Structure porteuse d''un agrément national organisme d''accueil communautaire et d''activité solidaire'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité ODC' then 'Organisation délégataire d''un CD'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité OIL' then 'Opérateur d''intermédiation locative'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité PE' then 'Pôle emploi'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité PENSION' then 'Pension de famille / résidence accueil'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité PIJ_BIJ' then 'PIJ-BIJ - Point/Bureau information jeunesse'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité PJJ' then 'PJJ - Protection judiciaire de la jeunesse'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité PLIE' then 'PLIE - Plan local pour l''insertion et l''emploi'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité PREVENTION' then 'Service ou club de prévention'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité RS_FJT' then 'Résidence sociale / FJT - Foyer de Jeunes Travailleurs'
        when candidatures_p.origine_détaillée = 'Prescripteur habilité SPIP' then 'SPIP - Service pénitentiaire d''insertion et de probation'
    end type_auteur_diagnostic_detaille,
    candidatures_p.région_structure,
    safir_org_prescripteur,
    id_org_prescripteur,
    nom_org_prescripteur,
    Nom_prénom_conseiller_pe,
    dept_org,
    région_org,
    injection_ai,
    ville,
    nom_epci,
    code_commune,
    nom_arrondissement,
    bassin_d_emploi,
    case
        when adherents_emmaus.reseau_emmaus = 'Emmaus' then 'Oui'
        else 'Non'
    end reseau_emmaus,
    case
        when adherents_coorace.reseau_coorace= 'Coorace' then 'Oui'
        else 'Non'
    end reseau_coorace,
    case
        when adherents_fei.reseau_fei= 'FEI' then 'Oui'
        else 'Non'
    end reseau_fei
from
    candidatures_p
        left join bassin_emploi
            on bassin_emploi.id_structure = candidatures_p.id_structure
        left join adherents_emmaus
            on adherents_emmaus.id_structure = candidatures_p.id_structure
        left join adherents_coorace
            on adherents_coorace.id_structure = candidatures_p.id_structure
        left join adherents_fei
            on adherents_fei.id_structure = candidatures_p.id_structure
        left join org_prescripteur
        	on org_prescripteur.id_org = candidatures_p.id_org_prescripteur
