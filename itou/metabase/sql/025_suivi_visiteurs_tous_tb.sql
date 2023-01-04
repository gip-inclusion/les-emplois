/* Dans cette table nous récupérons les infos des visiteurs uniques de Matomo à partir des tables créées par Victor qui automatisent les requêtes API */

with visiteurs_prives as (
    select
        svtp."Date" as semaine,
        /* Obligé de mettre les titres des colonnes entre "" sinon j'avais un message d'erreur de mon GUI */
        svtp."Tableau de bord" as tableau_de_bord,
        svtp."Visiteurs uniques" as visiteurs_uniques
    from
        suivi_visiteurs_tb_prives svtp /* Ancienne table créée par Victor qui débute en 2022 et s'arrête à la semaine du 12/12/22 */
),
visiteurs_prives_0 as (
    select
        to_date(svtp0."Date", 'YYYY-MM-DD') as semaine,
        svtp0."Tableau de bord" as tableau_de_bord,
        to_number(svtp0."Unique visitors", '99') as visiteurs_uniques
    from
        suivi_visiteurs_tb_prives_v0 svtp0 /* Nouvelle table créée par Victor qui démarre le 19/12/22 */
),
visiteurs_publics as (
    select
        to_date(vp."Date", 'YYYY-MM-DD') as semaine,
        vp."Tableau de bord" as tableau_de_bord,
        to_number(vp."Unique visitors", '99') as visiteurs_uniques
    from
        suivi_visiteurs_tb_publics_V0 vp /* Nouvelle table créée par Victor qui reprend toutes les infos des visiteurs des TBs publics */
)
select
    semaine,
    tableau_de_bord,
    visiteurs_uniques
from
    visiteurs_prives
where
    semaine is not null
union all
select
    semaine,
    tableau_de_bord,
    visiteurs_uniques
from
    visiteurs_prives_0
where
    semaine is not null
union all
select
    semaine,
    tableau_de_bord,
    visiteurs_uniques
from
    visiteurs_publics