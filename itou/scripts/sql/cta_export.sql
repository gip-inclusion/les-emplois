
-- France entière pour les Comités Technique d'Animation.
-- https://trello.com/c/XwYFC7Yc
--
-- Objectif métier : Amélioration des company TOUR. Export mensuel.
--
-- Champs demandés :
-- * Type de profil utilisateur : employeur, prescripteur habilité, orienteur
-- * Type d'établissement (EI,EA...PE,CCAS, autre...)
-- * Nom de l'établissement
-- * Nom et prénom de chaque membre
-- * Adresse email de chaque membre
-- * Le membre est admin de l'établissement (oui/non)
-- * Adresse
-- * Ville
-- * Code postal
-- * Département
-- * Région
-- * Date d'inscription du membre

create or replace function get_region_name(department varchar)
returns varchar as $$
    begin
        return case
            when department ~ ('^(01|03|07|15|26|38|42|43|63|69|73|74)') then 'Auvergne-Rhône-Alpes'
            when department ~ ('^(21|25|39|58|70|71|89|90)') then 'Bourgogne-Franche-Comté'
            when department ~ ('^(35|22|56|29)') then 'Bretagne'
            when department ~ ('^(18|28|36|37|41|45)') then 'Centre-Val de Loire'
            when department ~ ('^(2A|2B)') then 'Corse'
            when department ~ ('^(08|10|51|52|54|55|57|67|68|88)') then 'Grand Est'
            when department ~ ('^971') then 'Guadeloupe'
            when department ~ ('^973') then 'Guyane'
            when department ~ ('^(02|59|60|62|80)') then 'Hauts-de-France'
            when department ~ ('^(75|77|78|91|92|93|94|95)') then 'Île-de-France'
            when department ~ ('^974') then 'La Réunion'
            when department ~ ('^972') then 'Martinique'
            when department ~ ('^976') then 'Mayotte'
            when department ~ ('^(14|27|50|61|76)') then 'Normandie'
            when department ~ ('^(16|17|19|23|24|33|40|47|64|79|86|87)') then 'Nouvelle-Aquitaine'
            when department ~ ('^(09|11|12|30|31|32|34|46|48|65|66|81|82)') then 'Occitanie'
            when department ~ ('^(44|49|53|72|85)') then 'Pays de la Loire'
            when department ~ ('^(04|05|06|13|83|84)') then 'Provence-Alpes-Côte d''Azur'
            when department ~ ('^(975|977|978)') then 'Collectivités d''outre-mer'
            when department ~ ('^(986|987|988)') then 'Anciens territoires d''outre-mer'
        end;
    end;
$$ language plpgsql;


with company_data as (
    select
        'Employeur' as "Utilisateur - type",
        -- company
        company.kind as "Structure - type",
        company.name as "Structure - nom",
        company.address_line_1 as "Structure - adresse ligne 1",
        company.address_line_2 as "Structure - adresse ligne 2",
        company.post_code as "Structure - code postal",
        company.city as "Structure - ville",
        company.department as "Structure - département",
        get_region_name(company.department) as "Structure - région",

        -- user
        u.first_name as "Utilisateur - prénom",
        u.last_name as "Utilisateur - nom",
        u.email as "Utilisateur - e-mail",
        case
            when company_membership.is_admin is true then 'Oui' else 'Non'
        end as "Administrateur ?",
        to_char(u.date_joined, 'dd-mm-yyyy') as "Utilisateur - date d'inscription"
    from
        users_user as u
        inner join companies_companymembership as company_membership
            on (company_membership.user_id=u.id)
        inner join companies_company as company
            on (company.id=company_membership.company_id)
    where u.kind='employer' and company_membership.is_active
),

org_data as (
    select
        case
            when org.is_authorized is true then 'Prescripteur habilité' else 'Orienteur'
        end as "Utilisateur - type",
        -- org
        org.kind as "Structure - type",
        org.name as "Structure - nom",
        org.address_line_1 as "Structure - adresse ligne 1",
        org.address_line_2 as "Structure - adresse ligne 2",
        org.post_code as "Structure - code postal",
        org.city as "Structure - ville",
        org.department as "Structure - département",
        get_region_name(org.department) as "Structure - région",

        -- user
        u.first_name as "Utilisateur - prénom",
        u.last_name as "Utilisateur - nom",
        u.email as "Utilisateur - e-mail",
        case
            when prescriber_membership.is_admin is true then 'Oui' else 'Non'
        end as "Administrateur ?",
        to_char(u.date_joined, 'dd-mm-yyyy') as "Utilisateur - date d'inscription'"
    from
        users_user as u
        inner join prescribers_prescribermembership as prescriber_membership
            on (prescriber_membership.user_id=u.id)
        inner join prescribers_prescriberorganization as org
            on (org.id=prescriber_membership.organization_id)
    where u.kind='prescriber' and prescriber_membership.is_active
)

select * from company_data as company
    union all
        select * from org_data as org
 ;
