/* 
L'objectif est de calculer le délai entre la 1ère candidature et l'embauche des candidats orientés par PE:
- le nombre de candidats orientés par des prescripteurs habilités qui ont trouvé un emploi en IAE moins d 1 mois après leur première candidature 
- le nombre de candidats orientés par des prescripteurs habilités qui ont trouvé un emploi en IAE entre 1 mois et 2 mois après leur première candidature 
- le nombre de candidats orientés par des prescripteurs habilités qui ont trouvé un emploi en IAE entre 2 mois et 3 mois après leur première candidature 
- le nombre de candidats orientés par des prescripteurs habilités qui ont trouvé un emploi en IAE entre 3 mois et 4 mois après leur première candidature 
- le nombre de candidats orientés par des prescripteurs habilités qui ont trouvé un emploi en IAE entre 4 mois et 5 mois après leur première candidature 
- le nombre de candidats orientés par des prescripteurs habilités qui ont trouvé un emploi en IAE entre 5 mois et 6 mois après leur première candidature
*/

/* Trouver la date de la première candidature + date de la première embauche */

with date_1ere_candidature as (
    select 
        c.id_candidat,
        /* TODO dejafait drop as soon as analistos have migrated to the new deanonymized column */
        c.id_candidat_anonymisé,
        min(date_candidature) as date_1ere_candidature,
        min(
            case 
                when date_embauche is null then '2099-01-01'
                else date_embauche
            end) as date_1ere_embauche,
        candidats.nom_département as nom_département_candidat,
        date_candidature,
        date_embauche,
        origine,
        origine_détaillée, 
        id_org_prescripteur
    from 
        candidatures c 
    inner join candidats on c.id_candidat = candidats.id 
        where c.origine = 'Prescripteur habilité' /* Modification du filtre initialement fait par Soumia, qui n'était pas bon */
        and c.origine_détaillée  = 'Prescripteur habilité PE'
    group by 
        c.id_candidat,
        /* TODO dejafait drop as soon as analistos have migrated to the new deanonymized column */
        c.id_candidat_anonymisé,
        candidats.nom_département,
        date_candidature,
        date_embauche,
        origine,
        origine_détaillée, 
        id_org_prescripteur 
),
prescripteurs as (
    select 
        id,
        nom_département as nom_département_prescripteur /* Ajout du département du prescripteur pour les TBs privés */
    from organisations o 
)
select 
    id_candidat,
    /* TODO dejafait drop as soon as analistos have migrated to the new deanonymized column */
    id_candidat_anonymisé,
    nom_département_candidat,
    date_candidature,
    date_embauche,
    case 
        /* Division /30 pour passer du nombre de jour au mois */
        when ((date_1ere_embauche - date_1ere_candidature) / 30) < 1 then 'a- Moins d un mois'
        when ((date_1ere_embauche - date_1ere_candidature) / 30) >= 1 and ((date_1ere_embauche - date_1ere_candidature) /30) < 2 then 'b- Entre 1 et 2 mois'
        when ((date_1ere_embauche - date_1ere_candidature) / 30) >= 2 and ((date_1ere_embauche - date_1ere_candidature) /30) < 3 then 'c- Entre 2 et 3 mois'
        when ((date_1ere_embauche - date_1ere_candidature) / 30) >= 3 and ((date_1ere_embauche - date_1ere_candidature) /30) < 4 then 'd- Entre 3 et 4 mois'
        when ((date_1ere_embauche - date_1ere_candidature) / 30) >= 4 and ((date_1ere_embauche - date_1ere_candidature) /30) < 5 then 'e- Entre 4 et 5 mois'
        when ((date_1ere_embauche - date_1ere_candidature) / 30) >= 5 and ((date_1ere_embauche - date_1ere_candidature) /30) < 6 then 'f- Entre 5 et 6 mois'
        when ((date_1ere_embauche - date_1ere_candidature) / 30) >= 6 then 'g- 6 mois et plus'
    end délai_embauche,
    origine,
    origine_détaillée,
    id_org_prescripteur,
    nom_département_prescripteur
from 
    date_1ere_candidature
        left join prescripteurs p
            on p.id = date_1ere_candidature.id_org_prescripteur
/* Ecarter les candidats qui ne sont pas recrutés à aujourd'hui */    
where date_1ere_embauche != '2099-01-01'
