/*

Le besoin des DDETS est d'avoir un suivi en temps réel du retard que 
les structures prennent dans la saisie des données mensuelles 
dans l'extranet ASP avec pour chaque structure:
    - sa dénomination
    - sa commune
    - son siret
    - les numéros de convention
    - le nombre de mois de retard
    - le dernier mois saisi
    - saisie effectuée oui/non (saisie non effectuée si elle n'a pas été réalisée lors du mois précédent)
    - une adresse mail à contacter en cas de besoin de vérification
    
*/
with saisies as (
    select
        /* Récupérer le mois de la dernière déclaration faite par la structure 
        dans l'extranet ASP sous le format MM/YYYY */
        to_char(
            max(
                make_date(cast(emi.emi_sme_annee as integer), cast(emi.emi_sme_mois as integer), 1)
            ), 'MM/YYYY'
        ) as dernier_mois_saisi_asp,
        /* Calculer le nombre de mois de retard de saisie de la sructure dans l'extranet ASP par rapport au mois en cours */
        af.type_siae,
        af.af_id_annexe_financiere,
        af_numero_annexe_financiere,
        af.af_numero_convention,
        af.nom_departement_af,
        af.nom_region_af,
        structure.structure_denomination,
        structure.structure_adresse_admin_commune,
        structure.structure_id_siae,
        structure.structure_siret_actualise,
        structure.structure_adresse_mail_corresp_technique,
        /* Département et région calculés en se basant sur la commune administrative de la structure */
        structure.nom_departement_structure,
        structure.nom_region_structure
    from
        "fluxIAE_EtatMensuelIndiv" emi
    left join "fluxIAE_AnnexeFinanciere_v2" af
                on
        emi.emi_afi_id = af.af_id_annexe_financiere
                /* Ne prendre en compte que les structures qui ont une annexe financière 
                valide pour l'année en cours et prendre en compte les structures qui sont en retard de saisie dans l'asp */
        and af_etat_annexe_financiere_code in ('VALIDE')
        and date_part('year', af.af_date_debut_effet_v2) >= (
            date_part('year', current_date) - 1
        )
        -- Petite correction pour considérer les dates de saisie antérieures à 36 mois (parfois les annexes s'arrêtent en milieu d'année)
                and af.af_date_fin_effet_v2 >= CURRENT_DATE - INTERVAL '36 months'
                /* On prend les déclarations mensuelles de l'année en cours */
                and  emi.emi_sme_annee >= (date_part('year', current_date) - 1)
            left join "fluxIAE_Structure_v2" as structure
                on af.af_id_structure = structure.structure_id_siae  
    group by  
        af.type_siae, 
        af.af_id_annexe_financiere,
        af_numero_annexe_financiere, 
        af.af_numero_convention,
        af.nom_departement_af,
        af.nom_region_af,
        structure.structure_denomination,
        structure.structure_adresse_admin_commune, 
        structure.structure_id_siae,
        structure.structure_siret_actualise, 
        structure.structure_adresse_mail_corresp_technique, 
        structure.nom_departement_structure,
        structure.nom_region_structure
),
saisie_actualisee as (
    select 	
        structure_id_siae,
        structure_siret_actualise,
        af_id_annexe_financiere,
        af_numero_annexe_financiere,
        case /* On considère que la saisie est effectuée si elle a été faite lors du mois en cours ou précédent celui en cours */
            when to_date(dernier_mois_saisi_asp,'MM/YYYY') >= CURRENT_DATE - INTERVAL '2 months' then 'Oui'
            else 'Non'
        end saisie_effectuee
    from 
        saisies
)
select 
    dernier_mois_saisi_asp,
    saisie_effectuee, 
    type_siae, 
    saisies.af_id_annexe_financiere,
    saisies.af_numero_annexe_financiere, 
    af_numero_convention,
    nom_departement_af,
    nom_region_af,
    structure_denomination,
    structure_adresse_admin_commune, 
    saisies.structure_id_siae,
    saisies.structure_siret_actualise, 
    structure_adresse_mail_corresp_technique, 
    nom_departement_structure,
    nom_region_structure
from 
    saisies
        left join saisie_actualisee
	    on saisies.structure_id_siae = saisie_actualisee.structure_id_siae 
            and saisies.structure_siret_actualise = saisie_actualisee.structure_siret_actualise
	    and saisies.af_id_annexe_financiere = saisies.af_id_annexe_financiere 
            and saisies.af_numero_annexe_financiere = saisie_actualisee.af_numero_annexe_financiere