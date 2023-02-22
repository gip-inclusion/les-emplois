with nb_structures_par_dept as (
-- nb de structures référencées par dept
    select
        département,
        "nom_département",
        count(*) as nb_struct
    from
        structures
    group by
        "département",
        "nom_département"
)
select
    cap_camp.nom,
    struct."nom_département" as "nom_département",
    struct."région",
    -- récupération du pct de sélection attendu
    max(cap_camp."pourcentage_sélection") as "pct_sélection",
    --nb controlees : ie celles qui ont une date de contrôle non null
    sum(
        case when cap_struct."date_contrôle" is not null then
            1
        else
            0
        end) as nb_contrôlées,
    -- pourcentage de SIAE contrôlées :
    -- ie celles qui ont une date de contrôle non null
    -- sur toutes les SIAE référencées dans la table structure
    CAST(sum(
            case when cap_struct."date_contrôle" is not null then
                1
            else
                0
            end) as float) / max(nb_tot_dep.nb_struct) * 100 as "pct_contrôlées",
    -- nb de structures acceptées
    sum(case when cap_struct."état" = 'ACCEPTED' then
            1
        else
            0
        end) as "nb_acceptées",
    -- nb de structures refusées
    sum(case when cap_struct."état" = 'REFUSED' then
            1
        else
            0
        end) as "nb_refusées",
    -- nb de structures en attente notif
    sum(case when cap_struct."état" = 'NOTIFICATION_PENDING' then
            1
        else
            0
        end) as nb_attente
from
    cap_structures cap_struct
    left join structures struct on cap_struct.id_structure = struct.id
    left join cap_campagnes cap_camp on cap_camp.id = cap_struct.id_cap_campagne
    left join nb_structures_par_dept nb_tot_dep on nb_tot_dep."nom_département" = struct."nom_département"
group by
    cap_camp.nom,
    struct."région",
    struct."nom_département"
order by struct."nom_département";