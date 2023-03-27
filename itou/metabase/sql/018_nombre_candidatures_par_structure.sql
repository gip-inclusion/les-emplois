/* 

L'objectif est de créer une table agrégée avec le nombre de candidatures et le taux de candidature
selon l'état de la candidature, la structure, le type de structure, l'orgine de la candidature et le prescripteur

*/
with z_candidatures as (
    select
        c."état",
        c.date_candidature,
        count(c."état") as nombre_de_candidatures,
        c.id_structure,
        c.type_structure,
        c.nom_structure,
        c.injection_ai,
        c.origine,
        c."origine_détaillée",
        c."département_structure",
        c."nom_département_structure",
        c."région_structure",
        c.nom_org_prescripteur
    from
        public.candidatures c
    where
        type_structure in (
            'AI', 'ACI', 'EI', 'EITI', 'ETTI'
        )
    group by
        "état",
        c.date_candidature,
        id_structure,
        type_structure,
        nom_structure,
        injection_ai,
        origine,
        "origine_détaillée",
        "département_structure",
        "nom_département_structure",
        "région_structure",
        nom_org_prescripteur
),
z_prop_candidatures as (
    select
        "état",
        sum(nombre_de_candidatures) as total_candidatures,
        id_structure
    from
        z_candidatures
    group by
        "état",
        id_structure
),
z_ttes_candidatures as (
    select
        sum(nombre_de_candidatures) as somme_candidatures,
        id_structure
    from
        z_candidatures
    group by
        id_structure
)
select
    z_candidatures."état",
    z_candidatures.date_candidature,
    z_candidatures.nombre_de_candidatures,
    z_prop_candidatures.total_candidatures,
    z_ttes_candidatures.somme_candidatures,
    /* calcul de la proportion de candidatures en % */
    z_candidatures.nombre_de_candidatures / z_prop_candidatures.total_candidatures as taux_de_candidatures,
    z_candidatures.nom_structure,
    z_candidatures.type_structure,
    z_candidatures.origine,
    z_candidatures."origine_détaillée",
    s.ville,
    z_candidatures."département_structure",
    z_candidatures."nom_département_structure",
    z_candidatures."région_structure",
    z_candidatures.nom_org_prescripteur,
    z_candidatures.id_structure,
    s.siret,
    z_candidatures.injection_ai
from
    z_candidatures
left join z_prop_candidatures 
		on
    z_candidatures."état" = z_prop_candidatures."état"
    and z_candidatures.id_structure = z_prop_candidatures.id_structure
left join z_ttes_candidatures
		on
    z_candidatures.id_structure = z_ttes_candidatures.id_structure
left join public.structures s 
		on
    z_candidatures.id_structure = s.id
