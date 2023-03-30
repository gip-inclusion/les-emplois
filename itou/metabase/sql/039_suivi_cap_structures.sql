select
    "id_cap_campagne",
    "cap_campagnes"."nom"           as nom_campagne,
    "cap_structures"."id_structure" as id_cap_structure,
    "structures"."id"               as id_structure,
    "structures"."type",
    "structures"."département"      as "département",
    "structures"."nom_département"  as "nom_département",
    "structures"."région"           as "région",
    "cap_structures"."état",
    case
        when
            "structures"."active" = 1 then
            'Oui'
        else
            'Non'
    end                             as active,
    case
        when
            "cap_structures"."date_contrôle" is not null then
            'Oui'
        else
            'Non'
    end                             as "controlee"
from
    "public"."structures"
left join "public"."cap_structures" on "structures"."id" = "cap_structures"."id_structure"
left join "cap_campagnes" on "cap_structures"."id_cap_campagne" = "cap_campagnes"."id";
