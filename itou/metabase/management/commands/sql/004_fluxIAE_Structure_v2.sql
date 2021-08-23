/*

L'objectif est de rajouter le nom du département et la région de la structure à la table ASP "fluxIAE_Structure"
  
*/

with structure_asp as (
    select 
        /* l'ASP préconise l'utilisation de l'adresse administrative pour récupérer la commune de la structure */
        case
            when trim(substr(trim(structure.structure_adresse_admin_code_insee), 1, char_length(structure.structure_adresse_admin_code_insee)-2)) like ('%97%') 
            then trim(substr(trim(structure.structure_adresse_admin_code_insee), 1, char_length(structure.structure_adresse_admin_code_insee)-2)) 
            when trim(substr(trim(structure.structure_adresse_admin_code_insee), 1, char_length(structure.structure_adresse_admin_code_insee)-2)) like ('%98%') 
            then trim(substr(trim(structure.structure_adresse_admin_code_insee), 1, char_length(structure.structure_adresse_admin_code_insee)-2)) 
            else trim(substr(trim(structure.structure_adresse_admin_code_insee), 1, char_length(structure.structure_adresse_admin_code_insee)-3))
        end code_departement,
        * 
    from 
        "fluxIAE_Structure" as structure
)
select 
    dept_structure.nom_departement as nom_departement_structure,
    dept_structure.nom_region as nom_region_structure,
    structure.*
from 
    structure_asp structure
    left join "departements" dept_structure
        on dept_structure.code_departement = structure.code_departement
