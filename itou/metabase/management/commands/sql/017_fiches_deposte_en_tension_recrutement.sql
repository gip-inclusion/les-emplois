/*
 L'objectif est définir une fiche de poste en difficulté de recrutement
 Une fiche de poste est considérée en difficulté de recrutement si :
- elle est active 
    (l'employeur a déclaré sur les emplois de l'inclusion que le recrutement est ouvert sur cette fiche de poste)
- et sans recrutement sur les 30 derniers jours
    (fiches de poste sans candidatures sur les 30 derniers jours ou avec des candidatures mais sans recrutement)
- et a été publiée depuis plus de 30 jours
  En moyenne une fiche de poste reçoit une première candidature 30 jours après sa création 
  ==> alors toutes les fiches de poste qui ont au moins 30 jours d'ancienneté font partie du périmètre de l'analyse
- l’employeur n'a pas refusé des candidatures dans les 30 derniers jours pour le motif “Pas de poste ouvert
*/
with fdp_structures as (
    select 
        (current_date - fdp.date_création) as delai_mise_en_ligne,
        fdp.département_employeur as département_structure,
        fdp.id_employeur as id_structure,
        fdp.nom_département_employeur as nom_département_structure,
        s.nom as nom_structure, /* On récupère les infos via la table structure pour éviter des lignes vides lors de la recupération des infos candidatures */
        fdp.type_employeur as type_structure ,
        fdp.recrutement_ouvert as recrutement_ouvert_fdp,
        crdp.grand_domaine,
        crdp.domaine_professionnel,
        fdp.code_rome as code_rome_fpd,
        fdp.date_création as date_création_fdp,
        fdp.date_mise_à_jour_metabase,
        fdp.id as id_fdp,
        fdp.nom_rome as nom_rome_fdp,
        fdppc.id_anonymisé_candidature, 
        fdp.siret_employeur
    from 
        fiches_de_poste fdp 
    left join 
        fiches_de_poste_par_candidature fdppc 
        on fdp.id = fdppc.id_fiche_de_poste
    left join 
        code_rome_domaine_professionnel as crdp 
        on fdp.code_rome = crdp.code_rome 
    left join 
        structures s
        on s.id = fdp.id_employeur 
),
/*ici, contrairement à avant, on ne récupère que les infos des candidatures pour éviter des lignes vides */
candidatures_recues_par_fiche_de_poste as (
    select 
        c.date_candidature,
        c.date_embauche,
        c.délai_de_réponse,
        (current_date - c.date_candidature) as anciennete_candidature,
        fdp_s.delai_mise_en_ligne,
        (date_embauche - date_candidature) as delai_embauche, /* nous donne un délai en jours */
        c.délai_prise_en_compte,
        fdp_s.département_structure,
        c.id_anonymisé as id_candidature_anonymisé,
        c.id_candidat_anonymisé ,
        fdp_s.id_structure,
        c.motif_de_refus,
        fdp_s.nom_département_structure,
        c.nom_org_prescripteur,
        fdp_s.nom_structure,
        c.origine as origine_candidature,
        c.origine_détaillée as origine_détaillée_candidature,
        c.région_structure,
        c.safir_org_prescripteur,
        fdp_s.type_structure ,
        c.état as état_candidature,
        fdp_s.recrutement_ouvert_fdp,
        fdp_s.grand_domaine,
        fdp_s.domaine_professionnel,
        fdp_s.code_rome_fpd,
        fdp_s.date_création_fdp,
        fdp_s.date_mise_à_jour_metabase,
        fdp_s.id_fdp,
        fdp_s.nom_rome_fdp,
        fdp_s.siret_employeur
    from 
        fdp_structures fdp_s
    left join 
        candidatures c
        on c.id_anonymisé = fdp_s.id_anonymisé_candidature 
),
fiche_de_poste as (
    select 
        recrutement_ouvert_fdp,
        id_fdp,
        nom_rome_fdp,
        siret_employeur,
        id_structure,
        type_structure,
        nom_département_structure,
        département_structure,
        nom_structure,
        min(date_candidature) as date_1ere_candidature,
        max(date_candidature) as date_derniere_candidature_recue,
        max(date_embauche) as date_derniere_embauche,
        delai_mise_en_ligne,
        date_création_fdp,
        /* Délai entre la date de création des fiches de poste et la 1ère candidature */
        (min(date_candidature) - date_création_fdp) as delai_crea_1ere_candidature,
        crdp.domaine_professionnel,
        crdp.grand_domaine,
        concat(code_rome_fpd, '-', nom_rome_fdp) as rome,
        s.ville
    from 
        candidatures_recues_par_fiche_de_poste fdp    
    left join 
        code_rome_domaine_professionnel crdp
        on fdp.code_rome_fpd = crdp.code_rome
    left join
        structures s    
        on fdp.id_structure = s.id
    group by 
        recrutement_ouvert_fdp,
        id_fdp,
        id_structure,
        nom_rome_fdp,
        siret_employeur,
        type_structure,
        nom_département_structure,
        département_structure,
        nom_structure,
        delai_mise_en_ligne,
        date_création_fdp,
        crdp.domaine_professionnel,
        crdp.grand_domaine,
        concat(code_rome_fpd, '-', nom_rome_fdp),
        s.ville
),
/* 
Récupérer les identifiants de structures qui ont ont refusé des candidatures 
dans les 30 derniers jours pour le motif suivant “Pas de poste ouvert”
*/
id_structures_pas_poste_ouvert as (
    select 
        distinct id_structure,
        motif_de_refus
    from 
        candidatures_recues_par_fiche_de_poste fdp
    where 
        date_candidature >= date_trunc('month',  current_date) - interval '1 month'
        and 
        motif_de_refus = 'Pas de recrutement en cours'
),
/* Nombre de jours nécessaires pour qu'une fiche de poste reçoit une première candidature */
delai_1_ere_candidature as (
    select 
        30 as delai_moyen_crea_1ere_candidature
),
/* Identifier les fiches de poste qui ont reçu une candidature ou embauché dans les 30 derniers jours */
fiches_de_poste_avec_candidature as (  
    select 
        tab1.*,
        case 
            when date_derniere_candidature_recue 
                >= date_trunc('month',  current_date) - interval '1 month' 
            then 1
            else 0 
        end recu_candidatures_dernieres_30_jours, 
        case 
            when date_derniere_candidature_recue 
                is null 
            then 1
            else 0
        end jamais_candidatures_recues, 
        case 
            when date_derniere_embauche 
                >= date_trunc('month',  current_date) - interval '1 month' 
            then 1
            else 0 
        end embauche_30_derniers_jours,
        case 
            when tab1.id_structure in ( select id_structure from id_structures_pas_poste_ouvert )
            then 1
            else 0
        end structure_pas_poste_ouvert,    
        delai_moyen_crea_1ere_candidature
    from 
        delai_1_ere_candidature
    cross join 
        fiche_de_poste as tab1
    left join
        id_structures_pas_poste_ouvert s
        on tab1.id_structure = s.id_structure
),
etapes_entonnoir as (  
    select
        domaine_professionnel,
        grand_domaine,
        rome,
        nom_département_structure,
        département_structure,
        type_structure,
        id_structure,
        nom_structure,
        ville,
        count(distinct(id_fdp)) as "nb global fdp",
        count(distinct(id_fdp)) 
            filter 
                ( where recrutement_ouvert_fdp = 1 ) as "nb fdp actives",
        count(distinct(id_fdp)) 
            filter 
                ( where ( 
                    recrutement_ouvert_fdp = 1 and recu_candidatures_dernieres_30_jours = 0 )
                ) as "nb fdp sans candidatures dans les 30 derniers jours",
        count(distinct(id_fdp)) 
            filter 
                ( where (
                    ( recrutement_ouvert_fdp = 1 and recu_candidatures_dernieres_30_jours = 0 ) 
                    or 
                    ( recrutement_ouvert_fdp = 1 and embauche_30_derniers_jours = 0 ) )
                ) as "nb fdp sans candidatures ou sans embauche dans les 30 derniers jours ",
                
        count(distinct(id_fdp)) 
            filter 
                ( where (
                    ( recrutement_ouvert_fdp = 1  
                        and recu_candidatures_dernieres_30_jours = 0 
                        and structure_pas_poste_ouvert = 0 ) 
                    or 
                    ( recrutement_ouvert_fdp = 1 
                        and embauche_30_derniers_jours = 0 
                        and structure_pas_poste_ouvert = 0 ) )
                ) as "nb fdp sans embauche dans les 30 derniers jours et hors motif de refus-Pas de poste ouvert ",              
        count(distinct(id_fdp)) 
            filter 
                (where (
                    ( recrutement_ouvert_fdp = 1 
                        and recu_candidatures_dernieres_30_jours = 0 
                        and delai_mise_en_ligne >= delai_moyen_crea_1ere_candidature 
                        and structure_pas_poste_ouvert = 0
                        
                    ) or 
                    ( recrutement_ouvert_fdp = 1 
                        and embauche_30_derniers_jours = 0 
                        and delai_mise_en_ligne >= delai_moyen_crea_1ere_candidature
                        and structure_pas_poste_ouvert = 0 
                         ) )
               ) as "nb fiches de poste en difficulté de recrutement",
        count(distinct(id_fdp)) 
            filter 
                (where (
                    ( recrutement_ouvert_fdp = 1 
                        and recu_candidatures_dernieres_30_jours = 0 
                        and delai_mise_en_ligne >= delai_moyen_crea_1ere_candidature
                        and structure_pas_poste_ouvert = 0
                        and jamais_candidatures_recues = 1
                    ) or 
                    ( recrutement_ouvert_fdp = 1 
                        and embauche_30_derniers_jours = 0 
                        and delai_mise_en_ligne >= delai_moyen_crea_1ere_candidature
                        and structure_pas_poste_ouvert = 0
                        and jamais_candidatures_recues = 1) )
               ) as "nb fiches de poste en difficulté de recrutement n'ayant jamais reçu de candidatures"        
    from 
        fiches_de_poste_avec_candidature
    group by
        domaine_professionnel,
        grand_domaine,
        rome,
        nom_département_structure,
        type_structure,
        id_structure,
        nom_structure,
        département_structure,
        nom_rome_fdp,
        ville
)
select
    domaine_professionnel,
    grand_domaine,
    rome,
    nom_département_structure,
    département_structure,
    type_structure,
    id_structure,
    nom_structure,
    ville,
    '1- Fiches de poste' as  etape,
    "nb global fdp"    as  valeur
from    
    etapes_entonnoir
union all
    select
        domaine_professionnel,
        grand_domaine,
        rome,
        nom_département_structure,
        département_structure,
        type_structure,
        id_structure,
        nom_structure,
        ville,
        '2- Fiches de poste actives' as  etape,
        "nb fdp actives" as  valeur
    from   
        etapes_entonnoir
union all
    select
        domaine_professionnel,
        grand_domaine,
        rome,
        nom_département_structure,
        département_structure,
        type_structure,
        id_structure,
        nom_structure,
        ville,
        '3- Fiches de poste actives sans recrutement dans les 30 derniers jours' as  etape,
        "nb fdp sans candidatures ou sans embauche dans les 30 derniers jours"   as  valeur
    from   
        etapes_entonnoir
union all
    select
        domaine_professionnel,
        grand_domaine,
        rome,        
        nom_département_structure,
        département_structure,
        type_structure,
        id_structure,
        nom_structure,
        ville,
        '4- Fiches de poste actives sans recrutement dans les 30 derniers jours et sans motif pas de poste ouvert' as  etape,
        "nb fdp sans embauche dans les 30 derniers jours et hors motif de refus-Pas de poste ouvert"   as  valeur
    from    
        etapes_entonnoir                          
union all
    select
        domaine_professionnel,
        grand_domaine,
        rome,
        nom_département_structure,
        département_structure,
        type_structure,
        id_structure,
        nom_structure,
        ville,
        '5- Fiches de poste en difficulté de recrutement' as  etape,
        "nb fiches de poste en difficulté de recrutement"    as  valeur
    from    
        etapes_entonnoir                          
union all
    select
        domaine_professionnel,
        grand_domaine,
        rome,
        nom_département_structure,
        département_structure,
        type_structure,
        id_structure,
        nom_structure,
        ville,
        '6- Fiches de poste en difficulté de recrutement n ayant jamais reçu de candidatures' as  etape,
        "nb fiches de poste en difficulté de recrutement n'ayant jamais reçu de candidatures"   as  valeur
    from    
        etapes_entonnoir
