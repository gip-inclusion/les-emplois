    
/* 
     
L'objectif est de créer une table qui contient des informations à l'échelle locale (bassin d'emploi, epci, etc)
    
*/
    
with candidatures_p as ( 
    select  
        *
    from
        candidatures 
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
) 
select 
    date_candidature,
    date_embauche,
    délai_de_réponse,
    délai_prise_en_compte,
    candidatures_p.département_structure,
    état,
    id_anonymisé,
    id_candidat_anonymisé,
    candidatures_p.id_structure,
    motif_de_refus,
    candidatures_p.nom_département_structure,
    nom_structure,
    origine,
    origine_détaillée,
    candidatures_p.région_structure,
    safir_org_prescripteur,
    id_org_prescripteur,
    injection_ai,
    ville,
    nom_epci,
    code_commune,
    nom_arrondissement,
    bassin_d_emploi    
from 
    candidatures_p
        left join bassin_emploi
            on bassin_emploi.id_structure = candidatures_p.id_structure  
