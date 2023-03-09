select
    "criteres"."nom" as "nom_critère",
    "criteres"."id" as "id_critère",
    "criteres"."niveau" as "niveau_critère",
    -- REFUSED et REFUSED_2 correspondent au même état (?) - à confirmer par Zo
    case when "cap_criteres"."état" = 'REFUSED_2' then 'REFUSED' else "cap_criteres"."état" end as état,
    "camp"."nom" as "nom_campagne",
    "structs"."nom_département" as "nom_département",
    "structs"."région" as "nom_région",
    "structs"."type" as "type_structure"
from
    "cap_critères_iae" cap_criteres
    left join "critères_iae" criteres on cap_criteres."id_critère_iae" = criteres.id
    left join "cap_candidatures" candidatures on cap_criteres.id_cap_candidature = candidatures.id
    left join "cap_structures" cap_structs on candidatures.id_cap_structure = cap_structs.id
    left join "structures" structs on cap_structs.id_structure = structs.id
    left join "cap_campagnes" camp on cap_structs.id_cap_campagne = camp.id;
