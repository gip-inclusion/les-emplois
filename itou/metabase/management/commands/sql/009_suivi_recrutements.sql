/*

L'objectif est d'avoir un suivi annuel des recrutements en se basant sur les déclarations mensuelles des structures dans l'extranet asp

*/

select 
    /* On prend le min des dates de recrutement par salarié et par convention */
    min(date_recrutement) as min_date_recrutement,
    date_part('year', date_recrutement) as annee_recrutement, 
    etablissement_Public_Territorial, 
    niveau_formation_salarie,
    genre_salarie,
    rsa, 
    type_siae,
    identifiant_salarie,
    id_structure_asp, 
    structure_denomination,
    commune_structure, 
    code_insee_structure, 
    nom_departement_structure, 
    nom_region_structure,
    af_numero_convention,
    af_numero_annexe_financiere
from 
    saisies_mensuelles_IAE
group by 
    annee_recrutement,
    etablissement_Public_Territorial, 
    niveau_formation_salarie,
    genre_salarie,
    rsa, 
    type_siae,
    identifiant_salarie,
    id_structure_asp, 
    structure_denomination,
    commune_structure, 
    code_insee_structure, 
    nom_departement_structure, 
    nom_region_structure,
    af_numero_convention,
    af_numero_annexe_financiere
