/* L'objectif est de construire un tableau de bord pour suivre en début de chaque année
 les structures conventionnées (avec une annexe financière valide) */

/* Paramètres à changer tous les ans */
with constantes as (
    select
        2021 as annee_n_1,
        2022 as annee_n
),

structure_af as (
    select distinct
        af.af_id_structure             as identifiant_structure_asp,
        af.type_siae,
        af.af_mesure_dispositif_code,
        af.af_date_fin_effet_v2,
        af.af_etat_annexe_financiere_code,
        s.structure_denomination       as structure_denomination,
        s.structure_siret_actualise    as structure_siret,
        s.nom_departement_structure,
        s.nom_region_structure,
        s.code_departement,
        max(af.af_date_debut_effet_v2) as date_debut_af_plus_recente
    from
        "fluxIAE_AnnexeFinanciere_v2" as af
    left join "fluxIAE_Structure_v2" as s
        on af.af_id_structure = s.structure_id_siae
    where
        af_mesure_dispositif_code not like '%MP%' and af_mesure_dispositif_code not like '%FDI%'
    group by
        identifiant_structure_asp,
        af.type_siae,
        af.af_mesure_dispositif_code,
        af.af_date_fin_effet_v2,
        af.af_etat_annexe_financiere_code,
        structure_denomination,
        structure_siret,
        s.nom_departement_structure,
        s.nom_region_structure,
        s.code_departement
)

select distinct
    constantes.*,
    identifiant_structure_asp,
    type_siae,
    af_date_fin_effet_v2,
    structure_denomination,
    structure_siret,
    nom_departement_structure,
    nom_region_structure,
    code_departement,
    case
        when
            af_etat_annexe_financiere_code in ('VALIDE', 'PROVISOIRE')
            and date_debut_af_plus_recente >= make_date(cast(annee_n as integer), 1, 1)
            then 'AF_annee_n_valide'
        else 'AF_annee_n_nvalide'
    end as etat_af_annee_n
from constantes
cross join structure_af
/*Filter sur les structures qui avaient une annexe financière valide à fin Décembre de l'année n-1*/
where af_date_fin_effet_v2 >= make_date(cast(annee_n_1 as integer), 12, 31)
