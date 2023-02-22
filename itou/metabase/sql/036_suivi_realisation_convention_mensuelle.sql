select
    scec.id_annexe_financiere,
    scec.af_numero_convention,
    scec.af_numero_annexe_financiere,
    scec.af_etat_annexe_financiere_code,
    date_saisie,
    date_validation_declaration,
    case 
        when date_saisie is not null then 'Oui'
        else 'Non'
    end saisie_effectuee,
    case
        when nombre_heures_travaillees is not null then nombre_heures_travaillees
        else 0
    end nombre_heures_travaillees,
    case
        when nombre_etp_consommes_reels_annuels is not null then nombre_etp_consommes_reels_annuels
        else 0
    end nombre_etp_consommes_reels_annuels,
    case
        when nombre_etp_consommes_reels_mensuels is not null then nombre_etp_consommes_reels_mensuels
        else 0
    end nombre_etp_consommes_reels_mensuels,
    af_date_fin_effet_v2,
    annee_af,
    duree_annexe,
    effectif_mensuel_conventionné,
    effectif_annuel_conventionné,
    scec.type_structure,
    scec.structure_denomination,
    scec.commune_structure,
    scec.code_insee_structure,
    scec.siret_structure,
    scec.nom_departement_structure,
    scec.nom_region_structure,
    scec.code_departement_af,
    scec.nom_departement_af,
    scec.nom_region_af
from
    /*table créée en django */
    suivi_complet_etps_conventionnes scec
left join suivi_etp_realises_par_structure serps
    on
        serps.id_annexe_financiere = scec.id_annexe_financiere
    and serps.annee = scec.année
    and serps.mois = scec.month