/* Cette table nous permet de suivre la consommation d'etp par structures, par rapport à leur conventionnement */
select 
    etp.af_numero_convention,
    etp.af_numero_annexe_financiere,
    etp.date_saisie,
    annee_af,
    sum(nombre_etp_consommes_reels_mensuels) as total_etp_consommes_reels_mensuels,
    sum(nombre_etp_consommes_reels_annuels) as total_etp_consommes_reels_annuels,
    (etp_c.nombre_etp_conventionnés/12) as etp_conventionnés_par_mois, /* Je divise le conventionnement annuel par 12 pour que les SIAE puissent avoir une idée de leur conso vs conventionnement mensuelle */
    etp.type_structure,
    etp.structure_denomination,
    etp.code_departement_af,
    etp.nom_departement_af,
    etp.nom_region_af
from
    suivi_etp_realises_v2 etp
left join suivi_etp_conventionnes_v2 etp_c 
    on
    etp.af_numero_convention = etp_c.af_numero_convention
    and
    etp.af_numero_annexe_financiere = etp_c.af_numero_annexe_financiere
    and
    date_part('year',etp.date_saisie) = annee_af /* bien penser à joindre sur l'année pour éviter que l'on se retrouve avec années de conventionnement qui correspondent pas */
group by
    etp.af_numero_convention,
    etp.af_numero_annexe_financiere,
    etp_conventionnés_par_mois,
    annee_af,
    etp.date_saisie,
    etp.type_structure,
    etp.structure_denomination,
    etp.code_departement_af,
    etp.nom_departement_af,
    etp.nom_region_af