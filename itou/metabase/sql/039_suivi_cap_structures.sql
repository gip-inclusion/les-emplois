select
    id_cap_campagne,
    cap_campagnes.nom as nom_campagne,
    cap_structures.id_structure id_cap_structure,
    structures.id id_structure,
    structures.type,
    structures.nom_département as nom_département,
    structures."région" as région,
    structures.active as active,
    case when cap_structures. "date_contrôle" is not null then
        1
    else
        0
    end as "controlee",
    cap_structures.état
from
    "public"."structures" structures
    left join "public"."cap_structures" cap_structures on structures. "id" = cap_structures. "id_structure"
    left join "cap_campagnes" cap_campagnes on cap_structures.id_cap_campagne = cap_campagnes.id;