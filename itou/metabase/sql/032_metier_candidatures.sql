select
    id_candidat,
    id_candidature,
    id_fiche_de_poste id_structure,
    nom_structure,
    département_structure,
    nom_département_structure,
    type_structure,
    origine,
    origine_détaillée,
    type_auteur_diagnostic_detaille,
    région_structure,
    date_candidature,
    date_embauche,
    état,
    département_employeur,
    nom_département_employeur domaine_professionnel,
    grand_domaine,
    crdp.code_rome,
    nom_rome
from
    candidatures_echelle_locale cel
    inner join fiches_de_poste_par_candidature_v2 fdpc on fdpc.id_candidature = cel.id
    inner join fiches_de_poste fdp on fdpc.id_fiche_de_poste = fdp.id
    inner join code_rome_domaine_professionnel crdp on fdp.code_rome = crdp.code_rome
