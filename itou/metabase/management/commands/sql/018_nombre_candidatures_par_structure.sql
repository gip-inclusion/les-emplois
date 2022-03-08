/* 

L'objectif est de créer d'une table agrégée avec le nombre de candidatures et le taux de candidature
selon l'état de la candidture, la structure, le type de structure, l'orgine de la candidature et le préscripteur

*/

with candidatures as (
 	select 
		c.état,
		count(c.état) as nombre_de_candidatures,
		c.id_structure, 
		c.type_structure, 
		c.nom_structure,
		c.injection_ai,
		c.origine,
		c.département_structure,
		c.nom_département_structure,
		c.région_structure,
		c.nom_org_prescripteur	
	from 
		public.candidatures c 
	group by 
		état,
		id_structure,
		type_structure,
		nom_structure,
		injection_ai,
		origine,
		département_structure,
		nom_département_structure,
		région_structure,
		nom_org_prescripteur
),
prop_candidatures as ( 					
	select 
		état,
		sum(nombre_de_candidatures) as total_candidatures,
		id_structure 	
	from 
		candidatures
	group by 
		état,
		id_structure
)
select 
	candidatures.état,
	candidatures.nombre_de_candidatures,
	prop_candidatures.total_candidatures,
  /* calcul de la proportion de candidatures en % */
	candidatures.nombre_de_candidatures/prop_candidatures.total_candidatures*100 as taux_de_candidatures,  
	candidatures.nom_structure,
	candidatures.type_structure,
	candidatures.origine,
	s.ville,
	candidatures.département_structure,
	candidatures.nom_département_structure,
	candidatures.région_structure,
	candidatures.nom_org_prescripteur,
	candidatures.id_structure,
	candidatures.injection_ai
from
	candidatures
		left join prop_candidatures 
			on candidatures.état = prop_candidatures.état and candidatures.id_structure =  prop_candidatures.id_structure
		left join public.structures s 
			on candidatures.id_structure = s.id
