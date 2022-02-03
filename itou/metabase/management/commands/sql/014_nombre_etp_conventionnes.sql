/*

L'objectif est de suivre par année l'évolution du nombre d'ETP conventionnés en IAE par :
    -type de structure
    -département
    -région
 et de représenter sur une carte de france le nombre d'ETP conventionnés pour l'année en cours
 
 */
 
with constantes as 
( 
    select 
        max(date_part('year', af_date_debut_effet_v2)) as annee_en_cours
    from 
        "fluxIAE_AnnexeFinanciere_v2"
)
select
    distinct af.af_numero_convention,
    af.af_numero_annexe_financiere,
    date_part('year',af.af_date_debut_effet_v2) as annee_af,
    s.structure_denomination,
    s.structure_adresse_admin_commune as commune_structure, 
    s.structure_adresse_admin_code_insee as code_insee_structure,
    af.type_siae, 
    af.af_etp_postes_insertion as nombre_etp_conventionnés,
    af.nom_departement_af,
    af.nom_region_af,
    af.num_dep_af as code_departement_af
from 
    constantes
    cross join 
        "fluxIAE_AnnexeFinanciere_v2" as af 
    left join 
        "fluxIAE_Structure_v2" as s
        on af.af_id_structure = s.structure_id_siae  
 where          
    af.af_etat_annexe_financiere_code in ('VALIDE', 'PROVISOIRE')
    and date_part('year', af.af_date_debut_effet_v2) >= annee_en_cours - 2
    and af_mesure_dispositif_code not like '%MP%' 
    and af_mesure_dispositif_code not like '%FDI%'
