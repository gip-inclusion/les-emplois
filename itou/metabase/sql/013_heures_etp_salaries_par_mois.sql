/*
 
L'objectif est de créer une table agrégée avec par convention:
    - le nombre d'heures travaillées par les salariés en insertion
    - le nombre d'etp consommés
    - nombre de salarié en insertion
Ces indicateurs sont déclinés par type de public cible:
    - genre du salarié
    - RSA
    - niveau de formation du salarié
    - commune de la structure
    - établissement public territorial
    - établissements publics de coopération intercommunale
    - département et région de l'annexe financière
  
Un filtre est appliqué pour récupérer un historique de 2 ans en plus de l'année en cours
*/
with constantes as 
( 
select 
    max(date_part('year', date_saisie)) as annee_en_cours
from 
    saisies_mensuelles_IAE
) 
    select 
        identifiant_salarie,
        nombre_etp_consommes,
        nombre_heures_travaillees, 
        af_etp_postes_insertion as "nombre_etp_conventionnés",
        date_saisie,
        etablissement_Public_Territorial,
        nom_epci,
        niveau_formation_salarie,
        genre_salarie,
        rsa, 
        type_siae,
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
from 
    constantes 
    cross join 
        saisies_mensuelles_IAE
where 
    nombre_heures_travaillees > 0 
    and date_part('year', date_saisie) >= annee_en_cours - 2 
