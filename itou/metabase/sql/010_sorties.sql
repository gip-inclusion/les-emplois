/*
 
L'objectif est de créer une table agrégée avec l'indicateur nombre de sorties par type de public cible :
    - genre du salarié
    - RSA
    - niveau de formation du salarié
    - commune de la structure
    - établissement public territorial
    - établissements publics de coopération intercommunale
    - département et région de l'annexe financière
  
Un filtre est appliqué pour récupérer un historique de 2 ans en plus de l'année en cours
*/    

select 
    count(distinct(identifiant_salarie)) as nombre_sorties, 
    date_part('year', date_sortie) as annee_sortie,
    etablissement_Public_Territorial,
    nom_epci,
    niveau_formation_salarie,
    genre_salarie,
    rsa, 
    type_siae,
    type_structure,
    motif_sortie,
    categorie_sortie,
    id_structure_asp, 
    structure_denomination,
    commune_structure , 
    code_insee_structure, 
    nom_departement_af,
    nom_region_af,
    af_numero_convention,
    af_numero_annexe_financiere,    
    zrr,
    qpv,
    tranche_age,
    rqth
from 
    saisies_mensuelles_IAE
where 
    date_part('year', date_sortie) >= (date_part('year', current_date) - 2)
    /* Prendre en compte les salariés qui ont travaillé au moins une heure dans la structure */
    and nombre_heures_travaillees >= 1
group by 
    annee_sortie,  
    etablissement_Public_Territorial,
    nom_epci,
    niveau_formation_salarie,
    genre_salarie,
    rsa, 
    type_siae,
    type_structure,
    motif_sortie,
    categorie_sortie,
    id_structure_asp, 
    structure_denomination,
    commune_structure , 
    code_insee_structure, 
    nom_departement_af,
    nom_region_af,
    af_numero_convention,
    af_numero_annexe_financiere,
    zrr,
    qpv,
    tranche_age,
    rqth
