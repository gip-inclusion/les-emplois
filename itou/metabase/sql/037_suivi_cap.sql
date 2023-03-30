create table suivi_cap as
with nb_structures_par_dept as (
    select
        "département",
        "nom_département",
        cast(count(*) as float) as nb_struct
    from
        structures
    group by
        "département",
        "nom_département"
),
cap_struct_counts as (
    select
        cap_struct.id_structure,
        cap_struct.id_cap_campagne,
        --nb controlees : ie celles qui ont une date de contrôle non null
        cast(sum(
                case when cap_struct. "date_contrôle" is not null then
                    1
                else
                    0
                end) as float) as "nb_contrôlées",
        -- nb de structures acceptées
        cast(sum(
                case when cap_struct. "état" = 'ACCEPTED' then
                    1
                else
                    0
                end) as float) as "nb_acceptées",
        -- nb de structures refusées
        cast(sum(
                case when cap_struct. "état" = 'REFUSED' then
                    1
                else
                    0
                end) as float) as "nb_refusées",
        -- nb de structures en attente notif
        cast(sum(
                case when cap_struct. "état" = 'NOTIFICATION_PENDING' then
                    1
                else
                    0
                end) as float) as nb_attente
    from
        cap_structures cap_struct
    group by
        cap_struct.id_cap_campagne,
        cap_struct.id_structure
)
select
    cap_camp.nom as "nom_campagne",
    struct. "nom_département" as "nom_département",
    struct. "région",
    -- récupération du pct de sélection attendu
    -- que l'on divise par 100 pour permettre l'affichage correct sur metabase
    cast(max(cap_camp. "pourcentage_sélection") as float)/100 as "part_structures_à_contrôler",
    sum(cap_struct_cnt. "nb_contrôlées") as "nb_contrôlées",
    sum(cap_struct_cnt. "nb_acceptées") as "nb_acceptées",
    sum(cap_struct_cnt. "nb_refusées") as "nb_refusées",
    sum(cap_struct_cnt. "nb_attente") as "nb_attente",
    -- pourcentage de SIAE contrôlées :
    -- les contrôlées / ttes les siae
    sum(cap_struct_cnt. "nb_contrôlées") / max(nb_tot_dep.nb_struct) as "part_structures_contrôlées"
from
    cap_struct_counts cap_struct_cnt
    left join structures struct on cap_struct_cnt.id_structure = struct.id
    left join cap_campagnes cap_camp on cap_camp.id = cap_struct_cnt.id_cap_campagne
    left join nb_structures_par_dept nb_tot_dep on nb_tot_dep. "nom_département" = struct. "nom_département"
where struct.active = 1
group by
    cap_camp.nom,
    struct. "région",
    struct. "nom_département"
order by
    struct. "nom_département";
