select 
    origine_détaillée, 
    date_candidature, 
    count(distinct(id_candidat)) filter (where(état = 'Candidature acceptée')) as nombre_candidats_acceptés,
    count(distinct(id_candidat)) as nombre_candidats,
    count(distinct(id)) filter (where(état = 'Candidature acceptée')) as nombre_candidatures_acceptées,
    count(distinct(id)) as nombre_candidatures,
    injection_ai
from 
    candidatures
where 
    lower(origine_détaillée) like 'prescripteur%'
group by 
    origine_détaillée, 
    date_candidature,
    injection_ai 
