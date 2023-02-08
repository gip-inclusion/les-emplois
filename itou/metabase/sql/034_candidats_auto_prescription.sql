with auto_p as (
    select
        distinct(c.id),
        cd.état,
        c.age,
        c.département,
        c.nom_département,
        c.région,
        c.adresse_en_qpv,
        c.total_candidatures,
        c.total_embauches,
        c.date_diagnostic,
        c.id_auteur_diagnostic_employeur,
        c.type_auteur_diagnostic,
        c.sous_type_auteur_diagnostic,
        c.nom_auteur_diagnostic,
        cd.nom_structure,
        cd.département_structure,
        cd.nom_département_structure,
        cd.région_structure,
        /* on considère que l'on a de l'auto prescription lorsque l'employeur est l'auteur du diagnostic et effectue l'embauche */
        /* En créant une colonne on peut comparer les candidatures classiques à l'auto prescription */
        case
            when c.type_auteur_diagnostic = 'Employeur'
            and cd.origine = 'Employeur'
            and c.id_auteur_diagnostic_employeur = cd.id_structure then 'Autoprescription'
            else 'parcours classique'
        end type_de_candidature,
        case
            when c.injection_ai = 0 then 'Non'
            else 'Oui'
        end reprise_de_stock_ai_candidats
    from
        candidatures cd
    left join candidats c
    on
        cd.id_candidat = c.id
    where 
        état = 'Candidature acceptée'
        and c.type_auteur_diagnostic = 'Employeur'
        and cd.origine = 'Employeur'
        and c.id_auteur_diagnostic_employeur = cd.id_structure
),
all_candidates as (
    select
        c2.id,
        count(c2.id) as total_candidats
    from candidats c2
    left join candidatures cd2
        on 
            c2.id = cd2.id_candidat 
    where cd2.état = 'Candidature acceptée'
    group by c2.id
)
select
    *
from
    auto_p
left join all_candidates ac
    on 
        auto_p.id = ac.id