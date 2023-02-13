with siae_autopr as (
    select 
        count (
            distinct (id_structure)
        ) as total_siae_autopr,
        type_structure
    from
        suivi_auto_prescription sap
    where
        type_de_candidature = 'Autoprescription'
    group by 
        type_structure
),
siae_all as (
    select 
        count (
            distinct (id_structure)
        ) as total_siae_all,
        type_structure
    from
        suivi_auto_prescription sap
    group by 
        type_structure
)
select
    total_siae_autopr as "Nombre de structures utilisant l'autoprescription",
    total_siae_all as "Nombre total de structures",
    sau.type_structure
from
    siae_autopr sau
left join siae_all sall 
    on sau.type_structure = sall.type_structure