with siae_auto as (
    select 
        count (
            distinct (nom_structure)
        ) as siae_autop,
        1 as id
    from
        suivi_auto_prescription sap
    where
        type_de_candidature = 'Autoprescription'
),
siae_all as (
    select 
        count (
            distinct (nom_structure)
        ) as siae_all_p,
        1 as id
    from
        suivi_auto_prescription sap
)
select
    siae_autop as "Nombre de structures utilisant l'autoprescription",
    siae_all_p as "Nombre total de structures",
    cast (siae_autop as numeric)/cast (siae_all_p as numeric) as "% structures utilisant l'autoprescription"
from
    siae_auto sau
left join siae_all sall 
    on sau.id = sall.id