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
    - une adresse mail à contacter en cas de besoin de vérification
    
 */

select 
    /* Récupérer le mois de la dernière déclaration faite par la structure 
    dans l'extranet ASP sous le format MM/YYYY */
    to_char(
        max(
            make_date(cast(emi.emi_sme_annee as integer), cast(emi.emi_sme_mois as integer), 1)
        ), 'MM/YYYY'
    ) as dernier_mois_saisi_asp,
    /* Calculer le nombre de mois de retard de saisie de la sructure 
    dans l'extranet ASP par rapport au mois en cours */
    date_part('month', current_date ) - max(emi.emi_sme_mois) - 1 as retard_en_mois,
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
FROM 
    "fluxIAE_EtatMensuelIndiv" emi     
        left join "fluxIAE_AnnexeFinanciere_v2" af
            on emi.emi_afi_id = af.af_id_annexe_financiere
            /* Ne prendre en compte que les structures qui ont une annexe financière 
            valide  pour l'année en cours */
            and af_etat_annexe_financiere_code in ('VALIDE', 'SAISI')
            and date_part('year', to_date(af.af_date_debut_effet, 'dd/mm/yyyy')) = date_part('year', current_date)
            /* Ne prendre que les déclarations mensuelles de l'année en cours */
            and  emi.emi_sme_annee = date_part('year', current_date)
        left  join "fluxIAE_Structure_v2"  as structure
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
