with constantes as ( 
    /* historique de 2 ans */
    select 
        (max(emi.emi_sme_annee) - 2) as annee_en_cours_2, max(emi.emi_sme_annee) as annee_en_cours
    from 
        "fluxIAE_EtatMensuelIndiv" as emi
)
select 
    distinct emi.emi_pph_id as identifiant_salarie, /* ici on considère bien le salarié qu'une fois pour éviter des doublons et donc sur estimer les ETPs */
    emi.emi_afi_id as id_annexe_financiere,
    make_date(cast(emi.emi_sme_annee as integer), cast(emi.emi_sme_mois as integer), 1) as date_saisie,
    to_date (emi.emi_date_validation ,'dd/mm/yyyy') as date_validation_declaration,
    emi.emi_part_etp as nombre_etp_consommes_asp,
    emi.emi_nb_heures_travail as nombre_heures_travaillees,
    /*Nous calculons directement les ETPs réalisés pour éviter des problèmes de filtres/colonnes/etc sur metabase*/
    /* ETPs réalisés = Nbr heures travaillées / montant d'heures necessaires pour avoir 1 ETP */
    -- Ici le calcul nb heures * valeur nous donne de base des ETPs ANNUELS. 
    (emi.emi_nb_heures_travail / firmi.rmi_valeur) as nombre_etp_consommes_reels_annuels, 
    -- multiplication par 12 pour tomber sur le mensuel 
    (emi.emi_nb_heures_travail / firmi.rmi_valeur) * 12 as nombre_etp_consommes_reels_mensuels,
    emi.emi_afi_id as identifiant_annexe_fin,
    af.af_numero_convention,
    af.af_numero_annexe_financiere,
    af.af_etat_annexe_financiere_code,
    firmi.rmi_libelle,
    firmi.rmi_valeur,
    af.af_mesure_dispositif_code,
    type_structure,
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
    "fluxIAE_EtatMensuelIndiv" as emi
left join "fluxIAE_AnnexeFinanciere_v2" as af 
        on
    emi.emi_afi_id = af.af_id_annexe_financiere
    and emi.emi_sme_annee >= annee_en_cours_2
left join "fluxIAE_RefMontantIae" firmi 
        on
    af_mesure_dispositif_id = firmi.rme_id
left join "fluxIAE_Structure_v2" as structure
        on
    af.af_id_structure = structure.structure_id_siae
left join ref_mesure_dispositif_asp as ref_asp 
        on
    af.af_mesure_dispositif_code = ref_asp.af_mesure_dispositif_code
where
    emi.emi_sme_annee >= annee_en_cours_2
    and firmi.rmi_libelle = 'Nombre d''heures annuelles théoriques pour un salarié à taux plein'
    and af.af_etat_annexe_financiere_code in ('VALIDE', 'PROVISOIRE', 'CLOTURE')
    and af.af_mesure_dispositif_code not like '%FDI%'