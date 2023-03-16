with siae_autopr as (
    select 
        count (
            distinct (id_structure)
        ) as total_siae_autopr,
        type_structure,
        date_part('year',date_diagnostic) as annee_diagnostic
    from
        suivi_auto_prescription sap
    where
        type_de_candidature = 'Autoprescription' and active = 1
    group by 
        type_structure,
        annee_diagnostic
),
siae_all as (
    select 
        count (
            distinct (id_structure)
        ) as total_siae_all,
        type_structure,
        date_part('year',date_diagnostic) as annee_diagnostic
    from
        suivi_auto_prescription sap
    where 
        active = 1
    group by 
        type_structure,
        annee_diagnostic
)
select
    total_siae_autopr as "Nombre de structures utilisant l'autoprescription",
    total_siae_all as "Nombre total de structures",
    sau.type_structure,
    sau.annee_diagnostic
from
    siae_autopr sau
left join siae_all sall 
    on 
        sau.type_structure = sall.type_structure
    and 
        sau.annee_diagnostic = sall.annee_diagnostic