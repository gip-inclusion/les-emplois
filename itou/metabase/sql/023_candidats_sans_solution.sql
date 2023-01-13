/*
 
L'objectif est de suivre le nombre de candidats sans solution à 30 jours et pourcentage de ces candidats dans la totalité des candidats:
    - nb candidats qui 30 jours après leur inscription restent sans candidatures 
ou 
    - avec candidatures dont l’état est différent de “acceptée”

*/
with candidature as ( 
    select  
        distinct (id_candidat) identifiant_candidat, 
	    date_candidature,
	    count(distinct (candidatures.id)) nombre_candidature,
	    état, 
	    date_inscription
   from 
       candidatures 
   left join 
       Candidats on id_candidat =  public.candidats.id 
   where 
       date_candidature <= date_trunc('month', date_inscription) + interval '1 month'
       and date_candidature >= date_inscription 
       and candidatures.injection_ai = 0 
       and candidats.injection_ai = 0
    group by 
        identifiant_candidat,
        date_candidature,
        date_inscription,
        état
order by 
        identifiant_candidat ),
/* Nb candidats qui 30 jours après leur inscription restent sans candidatures */
candidats_sans_candidatures as (
    select 
        distinct(identifiant_candidat),
        date_inscription
    from 
        candidature
    where 
        nombre_candidature = 0 ),
/* Nb candidats qui 30 jours après leur inscription ont candidaté mais dont l’état est différent de “acceptée” */
candidats_avc_candidature_acceptee as (
    select 
        identifiant_candidat,
        sum( 
            case
                when état = 'Candidature acceptée' then 1 
                else 0 
            end ) as nb_candidature_acceptee, 
        date_inscription
    from 
        candidature 
    group by 
        identifiant_candidat,
        date_inscription
    order by 
        identifiant_candidat ),

union_table as ( 
    select 
        * 
    from 
        candidats_sans_candidatures 
    union (
        select 
            identifiant_candidat,
            date_inscription  
        from 
            candidats_avc_candidature_acceptee 
        where 
            nb_candidature_acceptee=0 ) )
select 
    a.nombre_candidats_ss_solution, 
    a.date_inscription, 
    b.nombre_candidats
from (
    select 
        count(distinct (identifiant_candidat) )  as nombre_candidats_ss_solution,
        date_inscription
    from 
        union_table
    group by 
        date_inscription ) as a 
left join (
    select 
        count(distinct(id)) as nombre_candidats,
        date_inscription
    from candidats 
    where candidats.injection_ai = 0
    group by date_inscription 
    ) as b 
    on a.date_inscription = b.date_inscription
