/*
L'objectif est d'avoir un suivi annuel des recrutements en se basant sur les déclarations mensuelles des structures dans l'extranet asp
*/

select
    /* On prend le min des dates de recrutement par salarié et par convention */
    etablissement_public_territorial,
    nom_epci,
    niveau_formation_salarie,
    genre_salarie,
    rsa,
    type_siae,
    identifiant_salarie,
    id_structure_asp,
    structure_denomination,
    commune_structure,
    code_insee_structure,
    nom_departement_af,
    nom_region_af,
    af_numero_convention,
    af_numero_annexe_financiere,
    zrr,
    qpv,
    tranche_age,
    rqth,
    min(date_recrutement)               as min_date_recrutement,
    date_part('year', date_recrutement) as annee_recrutement
from
    saisies_mensuelles_iae
where date_part('year', date_recrutement) >= (date_part('year', current_date) - 2)
group by
    annee_recrutement,
    etablissement_public_territorial,
    nom_epci,
    niveau_formation_salarie,
    genre_salarie,
    rsa,
    type_siae,
    identifiant_salarie,
    id_structure_asp,
    structure_denomination,
    commune_structure,
    code_insee_structure,
    nom_departement_af,
    nom_region_af,
    af_numero_convention,
    af_numero_annexe_financiere,
    zrr,
    qpv,
    tranche_age,
    rqth
