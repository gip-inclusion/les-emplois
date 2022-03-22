	
/* 
	 
L'objectif est de créer une table agrégée sur les candidats et leur candidatures qui ne contient que les préscripteurs comme auteurs de diagnostics. 
Nous récupérons aussi différentes informations sur les structures à partir de la table organisation afin de mettre en place des filtres + précis
	
*/
	
with candidats_p as ( /* Ici on sélectionne les colonnes pertinentes à partir de la table candidats en ne prenant que les auteurs = Prescripteur */
    select  
	distinct cdd.id_anonymisé as id_candidat_anonymise, 
	cdd.actif,   
	cdd.age,    
	cdd.date_diagnostic, 
	cdd.département as departement_candidat,
	cdd.nom_département as nom_departement_candidat,
	cdd.région as region_candidat,
	cdd.type_auteur_diagnostic,
	cdd.sous_type_auteur_diagnostic, 
	cdd.total_candidatures, 
	cdd.total_diagnostics,
	cdd.total_embauches,
	cdd.type_inscription,
	cdd.injection_ai,
	cdd.pe_inscrit
    from
	public.candidats as cdd /* cdd pour CanDiDats */
    where type_auteur_diagnostic = ('Prescripteur')
),
	
candidatures_p as ( /* Ici on sélectionne les colonnes pertinentes à partir de la table candidatures */
    select 
	cddr.id_candidat_anonymisé  as id_candidat_anonymise, 
	cddr.id_structure as id_structure,
	cddr.date_candidature, 
	cddr.date_embauche,
	cddr.département_structure,
	cddr.nom_département_structure,
	cddr.état,
	cddr.motif_de_refus,
	cddr.nom_org_prescripteur,
	cddr.nom_structure,
	cddr.origine,
	cddr.origine_détaillée,
	cddr.région_structure,
	cddr.type_structure,
	cddr.injection_ai,
	cddr.id_org_prescripteur	
    from
	public.candidatures as cddr /* cddr pour CanDiDatuRes */
),
	
organisations_p as ( /* On ne prend que type et type complet, le reste n'étant pas intéressant pour le moment */
    select 
	orga.id as id_structure,
	orga.type,
	orga.type_complet
    from 
	public.organisations as orga
)
	
select /* On selectionne les colonnes finales qui nous intéressent */
    candidats_p.id_candidat_anonymise,
    age,     
    date_diagnostic, 
    departement_candidat,
    nom_departement_candidat,
    region_candidat,
    type_auteur_diagnostic,
    sous_type_auteur_diagnostic, 
    total_candidatures, 
    total_diagnostics,
    total_embauches,
    type_inscription,
    pe_inscrit,
    candidatures_p.id_structure,
    date_candidature, 
    date_embauche,
    département_structure,
    nom_département_structure,
    état,
    motif_de_refus,
    nom_org_prescripteur,
    nom_structure,
    origine,
    origine_détaillée,
    région_structure,
    type_structure,
    id_org_prescripteur,
    candidatures_p.injection_ai,
    candidats_p.injection_ai,
    type,
    type_complet
from 
    candidats_p
        left join candidatures_p
		on candidats_p.id_candidat_anonymise = candidatures_p.id_candidat_anonymise 
	left join organisations_p 
		on candidatures_p.id_structure = organisations_p.id_structure
