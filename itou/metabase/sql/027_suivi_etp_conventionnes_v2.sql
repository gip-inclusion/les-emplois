with constantes as 
(
    select
        max(date_part('year', af_date_debut_effet_v2)) as annee_en_cours
    from
        "fluxIAE_AnnexeFinanciere_v2"
)
select
    distinct af.af_id_annexe_financiere as id_annexe_financiere,
    af.af_numero_convention,
    af.af_numero_annexe_financiere,
    date_part('year', af.af_date_debut_effet_v2) as annee_af,
    af_date_debut_effet_v2,
    af_date_fin_effet_v2,
    (
        date_part('year', af_date_fin_effet_v2) - date_part('year', af_date_debut_effet_v2)
    ) as year_diff,
    /* we compute year_diff to anticipate an eventual consideration of the FDI structure, which can have an af that goes over two years */
    (
        date_part('year', af_date_fin_effet_v2) - date_part('year', af_date_debut_effet_v2)
    ) * 12 + (
        date_part('month', af_date_fin_effet_v2) - date_part('month', af_date_debut_effet_v2)
    ) + 1 as duree_annexe,
    /* I need to add 1 to the operation because postgre considers that between january 1st and december 31st of the same year, 11 months have passed not 11,xx nor 12. Thus, the artificial addition of an extra month to round the operation is needed */
    af.af_etat_annexe_financiere_code,
    af.af_mesure_dispositif_id,
    af.af_mesure_dispositif_code,
    af.af_numero_avenant_modification,
    af.af_etp_postes_insertion as effectif_mensuel_conventionné,
    (
        af.af_etp_postes_insertion *(
            (
                date_part('year', af_date_fin_effet_v2) - date_part('year', af_date_debut_effet_v2)
            ) * 12 + (
                date_part('month', af_date_fin_effet_v2) - date_part('month', af_date_debut_effet_v2)
            )+ 1
        )/ 12
    ) as effectif_annuel_conventionné,
    replace(af.af_mesure_dispositif_code, '_', ' ') as type_structure,
    structure.structure_denomination,
    structure.structure_adresse_admin_commune as commune_structure,
    structure.structure_adresse_admin_code_insee as code_insee_structure,
    structure.structure_siret_actualise as siret_structure,
    structure.nom_departement_structure,
    structure.nom_region_structure,
    af.num_dep_af as code_departement_af,
    af.nom_departement_af,
    af.nom_region_af
from
    constantes
cross join 
    "fluxIAE_AnnexeFinanciere_v2" as af
left join 
    "fluxIAE_Structure_v2" as structure
        on
    af.af_id_structure = structure.structure_id_siae
where
    date_part('year', af.af_date_debut_effet_v2) >= annee_en_cours - 2
    and af.af_etat_annexe_financiere_code in (
        'VALIDE', 'PROVISOIRE', 'CLOTURE'
    )
    and af_mesure_dispositif_code not like '%FDI%'