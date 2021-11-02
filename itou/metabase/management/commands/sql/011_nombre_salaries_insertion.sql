/*
 
 Pour les ACI et les EI ,pour chaque salarié si la date est comprise entre sa date de début de contrat et sa date de fin de contrat prévisionnelle 
 alors il est comptabilisé sauf si sa structure a déclaré une rupture de contrat.
 
*/

with mois_tmp as (
    select 
        distinct(make_date(cast(emi.emi_sme_annee as integer), cast(emi.emi_sme_mois as integer), 01)) as premier_jour
    from 
        "fluxIAE_EtatMensuelIndiv" as emi 
),

mois as (
    select  
        premier_jour ,
        (date_trunc('month',  premier_jour) + interval '1 month' - interval '1 day'):: date as dernier_jour
    from 
        mois_tmp
),

/* Traitements des dates de la table "fluxIAE_ContratMission"*/
contrats as (
    select 
        ctra.contrat_id_ctr,
        ctra.contrat_id_pph ,
        to_date (ctra.contrat_date_embauche, 'dd/mm/yyyy') as date_embauche,
                
        /* 
         On prend en compte la date de sortie définitive comme date de fin si :
        -la date de sortie définitive est non null et  inférieure à la date de fin prévisionnelle (rupture anticipée du contrat)
        -la date de sortie définitive est non null et la date de fin prévisionnelle est nulle 
        */
        case 
            when (to_date(ctra.contrat_date_fin_contrat, 'dd/mm/yyyy') >= to_date(ctra.contrat_date_sortie_definitive, 'dd/mm/yyyy') 
                and to_date(ctra.contrat_date_sortie_definitive, 'dd/mm/yyyy') is not null) 
                or (to_date(ctra.contrat_date_fin_contrat , 'dd/mm/yyyy') is null 
                and to_date(ctra.contrat_date_sortie_definitive, 'dd/mm/yyyy') is not null)
            then to_date(ctra.contrat_date_sortie_definitive, 'dd/mm/yyyy') 
        /* Remplacer les dates de fin vides par 2099-01-01 */
            when to_date(ctra.contrat_date_fin_contrat, 'dd/mm/yyyy') is null 
                and to_date(ctra.contrat_date_sortie_definitive, 'dd/mm/yyyy') is null
            then make_date(2099, 01, 01)
            else to_date(ctra.contrat_date_fin_contrat, 'dd/mm/yyyy')
        end date_fin_contrat,
        contrat_mesure_disp_code
    from 
        "fluxIAE_ContratMission" as ctra 
),
  
ACI_EI_contrats_mois as (
    select  
        distinct ctra.contrat_id_pph as identifiant_salarie,
        ctra.contrat_id_ctr,
        date_embauche,
        date_fin_contrat,
        mois.premier_jour as date_mois
    from 
        contrats ctra
        left join mois on date_embauche <= mois.dernier_jour and date_fin_contrat >= mois.premier_jour
    where contrat_mesure_disp_code in ('ACI_DC', 'EI_DC')
), 

/*
 
Pour les AI et les ETTI, la méthode retenue est différente. 
Le nombre de salarié en insertion est mesuré en prenant en compte les salariés ayant effectué un nombre d’heures positif au cours du mois considéré 
(en utilisant la table de suivi mensuel individualisé de l’ASP).

*/

AI_ETTI_contrats_mois as (
    select 
        distinct identifiant_salarie,
        date_saisie as date_mois
    from 
        saisies_mensuelles_IAE
    where nombre_heures_travaillees > 0 and type_siae in ('AI', 'ETTI')
),

union_salarie_mois as ( 
    select 
        identifiant_salarie,
        date_mois   
    from 
        ACI_EI_contrats_mois
union (
    select *
    from 
        AI_ETTI_contrats_mois)
)

select count(distinct identifiant_salarie) as nb_salaries_insertion,
       date_mois
from union_salarie_mois
group by date_mois
