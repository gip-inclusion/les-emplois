/* 
L'objectif est définir une fiche de poste en difficulté de recrutement 
 Une fiche de poste est considérée en difficulté de recrutement :
-elle est active 
    (l'employeur a déclaré sur les emplois de l'inclusion que le recrutement est ouvert sur cette fiche de poste)
-et sans recrutement sur les 30 derniers jours 
    (fiches de poste sans candidatures sur les 30 derniers jours ou avec des candidatures mais sans recrutement)
-et suffisamment ancienne 
    (avec un délai de mise en ligne supérieur à la moyenne du délai 
    entre la date de création d'une fiche de poste et la première candidature reçue)
exemple : Si en moyenne une fiche de poste reçoit une première candidature 40 jours après sa création 
          ==> alors toutes les fiches de poste qui ont au moins 40 jours d'ancienneté font partie du périmètre de l'analyse.
*/

with table_1 as (
    select 
        recrutement_ouvert_fdp,
        id_fdp,
        nom_rome_fdp,
        siret_employeur,
        type_structure,
        nom_département_structure,
        nom_structure,
        min(date_candidature) as date_1ere_candidature,
        max(date_candidature) as date_derniere_candidature_recue,
        max(date_embauche) as date_derniere_embauche,
        delai_mise_en_ligne,
        date_création_fdp,
        /* Délai entre la date de création des fiches de poste et la 1ère candidature */
        (min(date_candidature) - date_création_fdp) as delai_crea_1ere_candidature    
    from 
        candidatures_recues_par_fiche_de_poste fdp
    group by 
        recrutement_ouvert_fdp,
        id_fdp,
        nom_rome_fdp,
        siret_employeur,
        type_structure,
        nom_département_structure,
        nom_structure,
        delai_mise_en_ligne,
        date_création_fdp
),
/* Nombre de jours nécessaires pour qu'une fiche de poste reçoit une première candidature */

table_2 as (
    select 
        avg(delai_crea_1ere_candidature) as délai_moyen_crea_1ere_candidature
    from 
        table_1
    where recrutement_ouvert_fdp =1
),

/* Détecter les fiches de poste qui ont reçu une candidature ou embauché dans les 30 derniers jours */
table_3 as (   
    select 
        tab1.*,
        case 
            when date_derniere_candidature_recue 
                >= date_trunc('month',  current_date) - interval '1 month' 
            then 1
            else 0 
        end recu_candidaures_dernieres_30_jours , 
        case 
            when date_derniere_embauche 
                >= date_trunc('month',  current_date) - interval '1 month' 
            then 1
            else 0 
        end embauche_30_derniers_jours ,       
        délai_moyen_crea_1ere_candidature
    from 
        table_2 
    cross join 
        table_1 as tab1
),

table_4 as (
    select 
        nom_département_structure,
        nom_rome_fdp,
        type_structure,
        count(distinct(id_fdp)) as "nb global fdp",
        count(distinct(id_fdp)) 
            filter 
                (where recrutement_ouvert_fdp =1) as "nb fdp actives",
        count(distinct(id_fdp)) 
            filter 
                (where ( 
                    recrutement_ouvert_fdp =1 and recu_candidaures_dernieres_30_jours=0 )
                ) as "nb fdp sans candidatures dans les 30 derniers jours",
        count(distinct(id_fdp)) 
            filter 
                ( where (
                    ( recrutement_ouvert_fdp =1 and recu_candidaures_dernieres_30_jours=0 ) 
                    or 
                    ( recrutement_ouvert_fdp =1 and embauche_30_derniers_jours=0 ) )
                ) as "nb fdp sans candidatures ou sans embauche dans les 30 derniers jours ", 
        count(distinct(id_fdp)) 
            filter 
                (where (
                    ( recrutement_ouvert_fdp =1 
                        and recu_candidaures_dernieres_30_jours=0 
                        and delai_mise_en_ligne >= délai_moyen_crea_1ere_candidature 
                    )or 
                    ( recrutement_ouvert_fdp =1 
                        and embauche_30_derniers_jours=0 
                        and delai_mise_en_ligne >= délai_moyen_crea_1ere_candidature ) )
               ) as "nb fiches de poste en difficulté de recrutement"
    from 
        table_3
    group by 
        nom_département_structure,
        type_structure,
        nom_rome_fdp 
)

    SELECT 
        nom_département_structure,
        nom_rome_fdp,
        type_structure,
        '1- Fiches de poste' AS  etape,
        "nb global fdp"    AS  valeur
    FROM    
        table_4
    UNION ALL
        SELECT  
            nom_département_structure,
            nom_rome_fdp,
            type_structure,
            '2- Fiches de poste actives' AS  etape,
            "nb fdp actives"    AS  valeur
        FROM    
            table_4
    UNION ALL
        SELECT  
            nom_département_structure,
            nom_rome_fdp,
            type_structure,
            '3- Fiches de poste actives sans recrutement dans les 30 derniers jours' AS  etape,
            "nb fdp sans candidatures ou sans embauche dans les 30 derniers jours"   AS  valeur
        FROM    
            table_4
    UNION ALL
        SELECT  
            nom_département_structure,
            nom_rome_fdp,
            type_structure,
            '4- Fiches de poste en difficulté de recrutement' AS  etape,
            "nb fiches de poste en difficulté de recrutement"    AS  valeur
        FROM    
            table_4
