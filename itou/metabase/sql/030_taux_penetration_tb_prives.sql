/* Dans cette table nous regroupons les visiteurs uniques ainsi que le nombre et type d'utilisateurs des TBs privés afin de calculer le taux de pénétration */
with "visiteurs_utilisateurs_privés" as (
    select
        count (utilisateur) as nombre_utilisateurs,
        utilisateur,
        numero_departement as departement,
        "nom_département" as nom_departement
    from
        suivi_utilisateurs_tb_prives sutp
    group by
        utilisateur,
        numero_departement,
        "nom_département"
),
/* Création des tables intermédiaires avec création d'une colonne utilisateurs afin de faire les jointures avec la table utilisateurs */
visiteurs_prives as (
    select
        svtp."Date" as semaine,
        svtp."Tableau de bord" as tableau_de_bord,
        svtp."Visiteurs uniques" as visiteurs_uniques,
        case
            when svtp."Tableau de bord" = 'tb 160 - Facilitation de l''embauche DREETS/DDETS' then 'DREETS/DDETS'
            when svtp."Tableau de bord" = 'tb 117 - Données IAE DREETS/DDETS' then 'DREETS/DDETS'
            when svtp."Tableau de bord" = 'tb 162 - Fiches de poste en tension PE' then 'Pôle emploi'
            when svtp."Tableau de bord" = 'tb 169 - Taux de transformation PE' then 'Pôle emploi'
            when svtp."Tableau de bord" = 'tb 168 - Délai d''entrée en IAE' then 'Pôle emploi'
            when svtp."Tableau de bord" = 'tb 149 - Candidatures orientées PE' then 'Pôle emploi'
            when svtp."Tableau de bord" = 'tb 165 - Recrutement SIAE' then 'SIAE'
            when svtp."Tableau de bord" = 'tb 118 - Données IAE CD' then 'Conseil départemental'
            else null
        end utilisateur,
        svtp."Département" as departement,
        svtp."Nom Département" as nom_departement
    from
        suivi_visiteurs_tb_prives svtp /* Ancienne table créée par Victor qui débute en 2022 et s'arrête à la semaine du 12/12/22 */
),
visiteurs_prives_0 as (
    select
        to_date(svtp0."Date", 'YYYY-MM-DD') as semaine,
        svtp0."Tableau de bord" as tableau_de_bord,
        to_number(svtp0."Unique visitors", '99') as visiteurs_uniques,
        case
            when svtp0."Tableau de bord" = 'tb 160 - Facilitation de l''embauche DREETS/DDETS' then 'DREETS/DDETS'
            when svtp0."Tableau de bord" = 'tb 117 - Données IAE DREETS/DDETS' then 'DREETS/DDETS'
            when svtp0."Tableau de bord" = 'tb 162 - Fiches de poste en tension PE' then 'Pôle emploi'
            when svtp0."Tableau de bord" = 'tb 169 - Taux de transformation PE' then 'Pôle emploi'
            when svtp0."Tableau de bord" = 'tb 168 - Délai d''entrée en IAE' then 'Pôle emploi'
            when svtp0."Tableau de bord" = 'tb 149 - Candidatures orientées PE' then 'Pôle emploi'
            when svtp0."Tableau de bord" = 'tb 165 - Recrutement SIAE' then 'SIAE'
            when svtp0."Tableau de bord" = 'tb 118 - Données IAE CD' then 'Conseil départemental'
            else null
        end utilisateur,
        svtp0."Département" as departement,
        svtp0."Nom Département" as nom_departement
    from
        suivi_visiteurs_tb_prives_v1 svtp0 /* Nouvelle table créée par Victor qui démarre le 01/01/22 */
),
/* Tables finales utilisées pour l'union all */
visiteur_utilisateurs as (
    select
        semaine,
        tableau_de_bord,
        visiteurs_uniques,
        vup.utilisateur,
        vup.nombre_utilisateurs,
        vu.departement,
        vu.nom_departement
    from
        visiteurs_prives vu
    left join "visiteurs_utilisateurs_privés" vup
        on
        vu.utilisateur = vup.utilisateur
        and vu.departement = vup.departement
),
visiteur_utilisateurs_0 as (
    select
        semaine,
        tableau_de_bord,
        visiteurs_uniques,
        vup.utilisateur,
        vup.nombre_utilisateurs,
        vu.departement,
        vu.nom_departement
    from
        visiteurs_prives_0 vu
    left join "visiteurs_utilisateurs_privés" vup
        on
        vu.utilisateur = vup.utilisateur
        and vu.departement = vup.departement
)
select
    semaine,
    tableau_de_bord,
    visiteurs_uniques,
    utilisateur,
    nombre_utilisateurs,
    departement,
    nom_departement
from
    visiteur_utilisateurs
where
    semaine is not null
union all
select
    semaine,
    tableau_de_bord,
    visiteurs_uniques,
    utilisateur,
    nombre_utilisateurs,
    departement,
    nom_departement
from
    visiteur_utilisateurs_0
where
    semaine is not null
