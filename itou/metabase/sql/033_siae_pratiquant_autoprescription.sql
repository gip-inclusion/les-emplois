with siae_autopr as (
    select
        type_structure,
        "département_structure",
        "nom_département_structure",
        "région_structure",
        date_part('year', date_diagnostic) as annee_diagnostic,
        count(
            distinct id_structure
        )                                  as total_siae_autopr
    from
        suivi_auto_prescription
    where
        type_de_candidature = 'Autoprescription' and active = 1
    group by
        type_structure,
        "département_structure",
        "nom_département_structure",
        "région_structure",
        annee_diagnostic
),

siae_all as (
    select
        type_structure,
        "département_structure",
        "nom_département_structure",
        "région_structure",
        date_part('year', date_diagnostic) as annee_diagnostic,
        count(
            distinct id_structure
        )                                  as total_siae_all
    from
        suivi_auto_prescription
    where
        active = 1
    group by
        type_structure,
        "département_structure",
        "nom_département_structure",
        "région_structure",
        annee_diagnostic
)

select
    total_siae_autopr as "Nombre de structures utilisant l'autoprescription",
    total_siae_all    as "Nombre total de structures",
    sau.type_structure,
    sau."département_structure",
    sau."nom_département_structure",
    sau."région_structure",
    sau.annee_diagnostic
from
    siae_all as sau
left join siae_autopr as sall
    on
        sau.type_structure = sall.type_structure
        and
        sau.annee_diagnostic = sall.annee_diagnostic
        and
        sau."nom_département_structure" = sall."nom_département_structure"
        and
        sau."région_structure" = sall."région_structure"
