with visiteurs_prives as (
    select
        svtp."Date" as semaine,  /* Obligé de mettre les titres des colonnes entre "" sinon j'avais un message d'erreur de mon GUI */
        svtp."Tableau de bord" as tableau_de_bord,
        svtp."Visiteurs uniques" as visiteurs_uniques
    from suivi_visiteurs_tb_prives svtp 
),
visiteurs_publics as (
    select
        vp."Date" as semaine,
        vp."tableau de bord" as tableau_de_bord,
        vp."Unique visitors" as visiteurs_uniques
    from suivi_visiteurs_tb_publics vp 
)
select
    semaine,
    tableau_de_bord,
    visiteurs_uniques
from
    visiteurs_prives
where semaine is not null       
union all
    select
        semaine,
        tableau_de_bord,
        visiteurs_uniques
    from
        visiteurs_publics
