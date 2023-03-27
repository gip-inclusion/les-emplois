with autopr_all as ( 
    select
        c.id,
        cd.id as id_candidature,
        c.hash_nir,
        c.age,
        "c.département",
        "c.nom_département",
        "c.région",
        c.adresse_en_qpv,
        c.total_candidatures,
        c.total_embauches,
        c.date_diagnostic,
        date_part('year', c.date_diagnostic) as "année_diagnostic",
        cd.date_candidature,
        date_part('year', cd.date_candidature) as "année_candidature",
        c.id_auteur_diagnostic_employeur,
        c.type_auteur_diagnostic,
        c.sous_type_auteur_diagnostic,
        c.nom_auteur_diagnostic,
        "cd.état",
        cd.id_structure,
        cd.origine,
        "cd.origine_détaillée",
        cd.type_structure,
        cd.nom_structure,
        "cd.département_structure",
        "cd.nom_département_structure",
        "cd.région_structure",
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
        end reprise_de_stock_ai_candidats,
        case
            when cd.injection_ai = 0 then 'Non'
            else 'Oui'
        end reprise_de_stock_ai_candidatures
    from
        candidatures cd
    left join candidats c
        on
        cd.id_candidat = c.id
)
select 
    autopr_all.id,
    id_candidature,
    type_de_candidature,
    hash_nir,
    "autopr_all.département",
    "autopr_all.nom_département",
    "autopr_all.région",
    adresse_en_qpv,
    date_diagnostic,
    "année_diagnostic",
    date_candidature,
    "année_candidature",
    id_auteur_diagnostic_employeur,
    type_auteur_diagnostic,
    sous_type_auteur_diagnostic,
    nom_auteur_diagnostic,
    "état",
    origine,
    "origine_détaillée",
    autopr_all.id_structure,
    s.siret,
    s.active,
    type_structure,
    nom_structure,
    s.ville,
    "département_structure",
    "nom_département_structure",
    "région_structure",
    reprise_de_stock_ai_candidats,
    reprise_de_stock_ai_candidatures
from
    autopr_all 
left join structures s
    on autopr_all.id_structure = s.id