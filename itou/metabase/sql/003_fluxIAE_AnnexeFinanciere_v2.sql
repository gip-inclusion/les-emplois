/*
L'objectif est de retravailler les variables de la table fluxIAE_AnnexeFinanciere: 
    
    - extraire le numéro du département à partir du numéro de l'annexe financière, selon le dictionnaire des données ASP le numéro de l'annexe financière 
    (ex : ACI034150012) contient dans l'ordre: le type de structure, le département, les 2 derniers caractères du millésime, le numéro d’ordre de l’annexe
    - récupérer le type de structure de la colonne af.af_mesure_dispositif_code (ex : ACI_DC)
    - retraiter les variables dates qui sont au format string dans la table fluxIAE_AnnexeFinanciere
 A noter que 'af' signifie annexe financière
    
*/

with "AnnexeFinanciere_v1" as (
    select
        /* Reformatage de la colonne type de structure par exemple on passe de ACI_DC à ACI */
        trim(substr(
            af.af_mesure_dispositif_code,
            1,
            char_length(af.af_mesure_dispositif_code)-3
        )) as type_siae,
        /* Les dates dans les tables fluxIAE sont par défaut au format string */
        to_date(
            af.af_date_debut_effet, 'dd/mm/yyyy'
        ) as af_date_debut_effet_v2,
        to_date(
            af.af_date_fin_effet, 'dd/mm/yyyy'
        ) as af_date_fin_effet_v2,
        *
    from
        "fluxIAE_AnnexeFinanciere" af 
),
    "AnnexeFinanciere_v2" as (
        select
            /* Retirer le type de structure du numéro de l'annexe financière par exemple on passe de ACI034150012 à 034150012 */
            substring(
                trim(af.af_numero_annexe_financiere) from (length(af.type_siae)+ 1)
            ) as af_numero_annexe_financiere_v3, 
            *
        from
            "AnnexeFinanciere_v1" af 
),
    "AnnexeFinanciere_v3" as (
        select
            /* Extraire les 3 premiers caractères du af_numero_annexe_financiere_v3 qui correspondent au département de l'annexe 
            par exemple on passe de 034150012 à 034 */
            substring(
                af_numero_annexe_financiere_v3 from 1 for 3 
            ) as af_numero_annexe_financiere_v4,
            *
        from
            "AnnexeFinanciere_v2" af 
),
    "AnnexeFinanciere_v4" as (
        select
            case
                /* Exemple pour ACI034150012 on récupère 34, pour un numéro de département qui commence par 0 
                on récupère les 2 cacartères qui suivent le 0 */
                when 
                    substring(
                        trim(af_numero_annexe_financiere_v4) from 1 for 1
                    ) = '0' 
                then 
                    substring(
                        trim(af_numero_annexe_financiere_v4) from 2 for 2
                    )
                /* Gérer les numéros d'annexes financières du département 59 exemple ACI59VXX2010 */  
                when 
                    substring(
                        trim(af_numero_annexe_financiere_v4) from 1 for 2
                    ) = '59' 
                then 
                    substring(
                        trim(af_numero_annexe_financiere_v4) from 1 for 2
                    )
                /* Exemple pour ACI971160010 on récupère 971, pour un numéro de département qui ne commence pas par 0 
                on garde les 3 caractères du af_numero_annexe_financiere_v4 */
                else 
                    substring(
                        trim(af_numero_annexe_financiere_v4) from 1 for 3
                    )
            end num_dep_af, 
            af.*
        from
            "AnnexeFinanciere_v3" af 
)
select
    af.num_dep_af as numero_departement_af,
    structure.structure_denomination as denomination_structure,
    structure.nom_departement_structure,
    structure.nom_region_structure,
    dept_af.nom_departement as nom_departement_af,
    dept_af.nom_region as nom_region_af,
    af.*
from
    "AnnexeFinanciere_v4" as af
    left join "fluxIAE_Structure_v2" as structure 
        on af.af_id_structure = structure.structure_id_siae
    left join departements dept_af 
        on dept_af.code_departement = af.num_dep_af
