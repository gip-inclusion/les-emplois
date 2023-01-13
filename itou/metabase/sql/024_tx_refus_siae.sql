/* L'objectif est de suivre le taux de refus par type de structure */       
with etp_conventionnes as (
    select 
        type_siae,
        nom_departement_af,
        nom_region_af,
        sum(nombre_etp_conventionnés) as nombre_etp_conventionnes 
    from nombre_etp_conventionnes
    where annee_af = date_part('year', current_date) 
    group by 
        type_siae,
        nom_departement_af,
        nom_region_af 
    )
select 
    /* Nombre de candidatures acceptées initiées par l'employeur de type SIAE */
    count(distinct candidatures_echelle_locale.id) 
        filter (
            where 
                (origine = 'Employeur') 
                and (état = 'Candidature acceptée')
                and type_structure in ('EI', 'ETTI', 'AI', 'ACI', 'EITI')) as nombre_candidatures_acceptees_employeurs,
    /* Nombre de candidatures initiées par l'employeur de type SIAE */
    count(distinct candidatures_echelle_locale.id) 
        filter (
            where 
                (origine = 'Employeur') 
                and type_structure in ('EI', 'ETTI', 'AI', 'ACI', 'EITI')) as nombre_candidatures_employeurs,
    count(distinct candidatures_echelle_locale.id) 
        filter (
            where 
                (état = 'Candidature acceptée')
                and type_structure in ('EI', 'ETTI', 'AI', 'ACI', 'EITI')) as nombre_candidatures_acceptees,
    count(distinct id_fiche_de_poste) AS Nombre_fiches_poste_ouvertes, 
    count(distinct id) AS nombre_candidatures,
    count(distinct id) 
        filter (
            where (état = 'Candidature déclinée')) as nombre_candidatures_refusees,
    count(distinct id) 
        filter (
            where (état = 'Candidature déclinée')and origine != 'Employeur') as nb_candidatures_refusees_non_emises_par_employeur_siae,
    count(distinct id_structure) as nombre_siae,
    nombre_etp_conventionnes,
    type_structure,
    nom_département_structure,
    région_structure,
    candidatures_echelle_locale.ville,
    nom_epci,
    candidatures_echelle_locale.code_commune,
    nom_arrondissement,
    bassin_d_emploi    
from 
    candidatures_echelle_locale
left join 
    fiches_de_poste_par_candidature fdpc 
    on candidatures_echelle_locale.id = fdpc.id_candidature 
left join 
    fiches_de_poste fdp on fdpc.id_fiche_de_poste = fdp.id
left join 
    structures on structures.id =candidatures_echelle_locale.id_structure 
left join 
    etp_conventionnes 
        on etp_conventionnes.type_siae = candidatures_echelle_locale.type_structure
        and etp_conventionnes.nom_departement_af = candidatures_echelle_locale.nom_département_structure
        and etp_conventionnes.nom_region_af = candidatures_echelle_locale.région_structure
where 
    candidatures_echelle_locale.injection_ai = 0 
    and recrutement_ouvert = 1
     /*se restreindre aux 12 derniers mois*/
    and date_candidature >= date_trunc('month', CAST((CAST(now() AS timestamp) + (INTERVAL '-12 month')) AS timestamp)) 
    and type_structure  in ('EI', 'ETTI', 'AI', 'ACI', 'EITI')
group by 
    type_structure,
    nom_département_structure,
    région_structure,
    nombre_etp_conventionnes,
    candidatures_echelle_locale.ville,
    nom_epci,
    candidatures_echelle_locale.code_commune,
    nom_arrondissement,
    bassin_d_emploi 
