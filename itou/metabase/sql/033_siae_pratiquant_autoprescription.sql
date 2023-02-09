with siae_autopr as (
    select 
        count (
            distinct (id_structure)
        ) as total_siae_autopr,
        1 as id
    from
        suivi_auto_prescription sap
    where
        type_de_candidature = 'Autoprescription'
),
siae_all as (
    select 
        count (
            distinct (id_structure)
        ) as total_siae_all,
        1 as id
    from
        suivi_auto_prescription sap
)
select
    total_siae_autopr as "Nombre de structures utilisant l'autoprescription",
    total_siae_all as "Nombre total de structures",
    cast (total_siae_autopr as numeric)/cast (total_siae_all as numeric) as "% structures utilisant l'autoprescription"
from
    siae_autopr sau
left join siae_all sall 
    on sau.id = sall.id