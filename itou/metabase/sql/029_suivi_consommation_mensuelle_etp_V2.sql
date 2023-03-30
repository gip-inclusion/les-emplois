select distinct

    etp.af_numero_annexe_financiere,
    etp.af_numero_convention,
    date_saisie,
    annee_af,
    etp.af_etat_annexe_financiere_code,
    etp."effectif_mensuel_conventionné",
    etp."effectif_annuel_conventionné",
    etp.type_structure,
    etp.structure_denomination,
    etp.code_departement_af,
    etp.nom_departement_af,
    etp.nom_region_af,
    (etp.id_annexe_financiere),
    sum(nombre_etp_consommes_reels_mensuels)   as total_etp_mensuels_realises,
    sum(nombre_etp_consommes_reels_annuels)    as total_etp_annuels_realises,
    case
        when etp."effectif_mensuel_conventionné" != 0 then sum(nombre_etp_consommes_reels_mensuels) / etp."effectif_mensuel_conventionné" * 100
        else 0
    end                                        as taux_de_realisation,
    max(date_part('month', etp_c.date_saisie)) as mois_max
from
    suivi_etp_conventionnes_v2 as etp
left join suivi_etp_realises_v2 as etp_c
    on
        etp.id_annexe_financiere = etp_c.id_annexe_financiere
        and
        etp.af_numero_convention = etp_c.af_numero_convention
        and
        etp.af_numero_annexe_financiere = etp_c.af_numero_annexe_financiere
        and
        date_part('year', etp_c.date_saisie) = annee_af /* bien penser à joindre sur l'année pour éviter que l'on se retrouve avec années de conventionnement qui correspondent pas */
group by
    etp.id_annexe_financiere,
    etp.af_numero_convention,
    etp.af_numero_annexe_financiere,
    "effectif_mensuel_conventionné",
    "effectif_annuel_conventionné",
    etp.af_etat_annexe_financiere_code,
    date_saisie,
    annee_af,
    etp.type_structure,
    etp.structure_denomination,
    etp.code_departement_af,
    etp.nom_departement_af,
    etp.nom_region_af
