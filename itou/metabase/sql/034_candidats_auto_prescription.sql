with autopr_candidates as (
    select
        distinct(c.id),
        cd.état,
        c.age,
        c.total_critères_niveau_1,
        c.total_critères_niveau_2,
        c.critère_n1_bénéficiaire_du_rsa,
        c.critère_n1_allocataire_ass,
        c.critère_n1_allocataire_aah,
        c.critère_n1_detld_plus_de_24_mois,
        c.critère_n2_niveau_d_étude_3_cap_bep_ou_infra,
        c.critère_n2_senior_plus_de_50_ans,
        c.critère_n2_jeune_moins_de_26_ans,
        c.critère_n2_sortant_de_l_ase,
        c.critère_n2_deld_12_à_24_mois,
        c.critère_n2_travailleur_handicapé,
        c.critère_n2_parent_isolé,
        c.critère_n2_personne_sans_hébergement_ou_hébergée_ou_ayant_u,
        c.critère_n2_réfugié_statutaire_bénéficiaire_d_une_protectio,
        c.critère_n2_résident_zrr,
        c.critère_n2_résident_qpv,
        c.critère_n2_sortant_de_détention_ou_personne_placée_sous_main,
        c.critère_n2_maîtrise_de_la_langue_française,
        c.critère_n2_mobilité,
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
    autopr_c.id,
    état,
    age,
    total_critères_niveau_1,
    total_critères_niveau_2,
    critère_n1_bénéficiaire_du_rsa,
    critère_n1_allocataire_ass,
    critère_n1_allocataire_aah,
    critère_n1_detld_plus_de_24_mois,
    critère_n2_niveau_d_étude_3_cap_bep_ou_infra,
    critère_n2_senior_plus_de_50_ans,
    critère_n2_jeune_moins_de_26_ans,
    critère_n2_sortant_de_l_ase,
    critère_n2_deld_12_à_24_mois,
    critère_n2_travailleur_handicapé,
    critère_n2_parent_isolé,
    critère_n2_personne_sans_hébergement_ou_hébergée_ou_ayant_u,
    critère_n2_réfugié_statutaire_bénéficiaire_d_une_protectio,
    critère_n2_résident_zrr,
    critère_n2_résident_qpv,
    critère_n2_sortant_de_détention_ou_personne_placée_sous_main,
    critère_n2_maîtrise_de_la_langue_française,
    critère_n2_mobilité,
    département,
    nom_département,
    région,
    adresse_en_qpv,
    total_candidatures,
    total_embauches,
    date_diagnostic,
    id_auteur_diagnostic_employeur,
    type_auteur_diagnostic,
    sous_type_auteur_diagnostic,
    nom_auteur_diagnostic,
    nom_structure,
    département_structure,
    nom_département_structure,
    région_structure,
    total_candidats,
    type_de_candidature,
    reprise_de_stock_ai_candidats
from
    autopr_candidates as autopr_c
left join all_candidates ac
    on 
        autopr_c.id = ac.id