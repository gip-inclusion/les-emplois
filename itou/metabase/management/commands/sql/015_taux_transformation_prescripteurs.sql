	
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
	case /* On soustrait 6 mois à la date de diagnostic pour déterminer s'il est toujours en cours ou pas */
    	    when date_diagnostic >= CURRENT_DATE - INTERVAL '6 months' then 'Oui' 
    	    else 'non'
	end diagnostic_valide,
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
)
select /* On selectionne les colonnes finales qui nous intéressent */
    id_candidat_anonymise,
    actif,
    age,
    date_diagnostic,
    diagnostic_valide,
    departement_candidat,
    nom_departement_candidat,
    region_candidat,
    type_auteur_diagnostic,
    case /* Modification des noms pour plus de clarté */
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur AFPA' then 'AFPA - Agence nationale pour la formation professionnelle des adultes'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur ASE' then 'ASE - Aide sociale à l''enfance'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur Autre' then 'Autre' 
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CAARUD' then 'CAARUD - Centre d''accueil et d''accompagnement à la réduction de risques pour usagers de drogues'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CADA' then 'CADA - Centre d''accueil de demandeurs d''asile'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CAF' then 'CAF - Caisse d''allocations familiales'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CAP_EMPLOI' then 'CAP emploi'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CAVA' then 'ACAVA - Centre d''adaptation à la vie active'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CCAS' then 'CCAS - Centre communal d''action sociale ou centre intercommunal d''action sociale'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CHRS' then 'CHRS - Centre d''hébergement et de réinsertion sociale'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CHU' then 'CHU - Centre d''hébergement d''urgence'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CIDFF' then 'CIDFF - Centre d''information sur les droits des femmes et des familles'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CPH' then 'CPH - Centre provisoire d''hébergement'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur CSAPA' then 'CSAPA - Centre de soins, d''accompagnement et de prévention en addictologie'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur DEPT' then 'Service social du conseil départemental'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur E2C' then 'E2C - École de la deuxième chance'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur EPIDE' then 'EPIDE - Établissement pour l''insertion dans l''emploi'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur HUDA' then 'HUDA - Hébergement d''urgence pour demandeurs d''asile'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur ML' then 'Mission Locale'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur MSA' then 'MSA - Mutualité Sociale Agricole'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur None' then 'Autre'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur OACAS' then 'OACAS - Structure porteuse d''un agrément national organisme d''accueil communautaire et d''activité solidaire'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur ODC' then 'Organisation délégataire d''un CD'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur OIL' then 'Opérateur d''intermédiation locative'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur PE' then 'Pôle emploi'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur PENSION' then 'Pension de famille / résidence accueil'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur PIJ_BIJ' then 'PIJ-BIJ - Point/Bureau information jeunesse'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur PJJ' then 'PJJ - Protection judiciaire de la jeunesse'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur PLIE' then 'PLIE - Plan local pour l''insertion et l''emploi'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur PREVENTION' then 'Service ou club de prévention'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur RS_FJT' then 'Résidence sociale / FJT - Foyer de Jeunes Travailleurs'
	when candidats_p.sous_type_auteur_diagnostic = 'Prescripteur SPIP' then 'SPIP - Service pénitentiaire d''insertion et de probation'
    end type_auteur_diagnostic_detaille, 
    total_candidatures,
    total_diagnostics,
    total_embauches,
    type_inscription,
    pe_inscrit 
from 
    candidats_p
