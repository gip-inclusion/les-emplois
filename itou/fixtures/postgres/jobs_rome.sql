--
-- PostgreSQL database dump
--

-- Dumped from database version 15.4 (Debian 15.4-2.pgdg110+1)
-- Dumped by pg_dump version 16.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: jobs_rome; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.jobs_rome (code, name, updated_at) FROM stdin;
A1101	Conduite d'engins agricoles et forestiers	2024-09-17 16:56:00.336253+00
A1201	Bûcheronnage et élagage	2024-09-17 16:56:00.336273+00
A1202	Entretien des espaces naturels	2024-09-17 16:56:00.336282+00
A1203	Aménagement et entretien des espaces verts	2024-09-17 16:56:00.33629+00
A1204	Protection du patrimoine naturel	2024-09-17 16:56:00.336297+00
A1205	Sylviculture	2024-09-17 16:56:00.336305+00
A1301	Conseil et assistance technique en agriculture	2024-09-17 16:56:00.336312+00
A1302	Contrôle et diagnostic technique en agriculture	2024-09-17 16:56:00.336319+00
A1303	Ingénierie en agriculture et environnement naturel	2024-09-17 16:56:00.336327+00
A1401	Aide agricole de production fruitière ou viticole	2024-09-17 16:56:00.336335+00
A1402	Aide agricole de production légumière ou végétale	2024-09-17 16:56:00.336342+00
A1403	Aide d'élevage agricole et aquacole	2024-09-17 16:56:00.336349+00
A1404	Aquaculture	2024-09-17 16:56:00.336356+00
A1405	Arboriculture et viticulture	2024-09-17 16:56:00.336362+00
A1406	Encadrement équipage de la pêche	2024-09-17 16:56:00.33637+00
A1407	Élevage bovin ou équin	2024-09-17 16:56:00.336377+00
A1408	Élevage d'animaux sauvages ou de compagnie	2024-09-17 16:56:00.336386+00
A1409	Élevage de lapins et volailles	2024-09-17 16:56:00.336394+00
A1410	Élevage ovin ou caprin	2024-09-17 16:56:00.336401+00
A1411	Élevage porcin	2024-09-17 16:56:00.336408+00
A1412	Fabrication et affinage de fromages	2024-09-17 16:56:00.336415+00
A1413	Fermentation de boissons alcoolisées	2024-09-17 16:56:00.336422+00
A1414	Horticulture et maraîchage	2024-09-17 16:56:00.336429+00
A1415	Equipage de la pêche	2024-09-17 16:56:00.336436+00
A1416	Polyculture, élevage	2024-09-17 16:56:00.336443+00
A1417	Saliculture	2024-09-17 16:56:00.33645+00
A1501	Aide aux soins animaux	2024-09-17 16:56:00.336457+00
A1502	Podologie animale	2024-09-17 16:56:00.336464+00
A1503	Toilettage des animaux	2024-09-17 16:56:00.336472+00
A1504	Santé animale	2024-09-17 16:56:00.336479+00
B1101	Création en arts plastiques	2024-09-17 16:56:00.336486+00
B1201	Réalisation d'objets décoratifs et utilitaires en céramique et matériaux de synthèse	2024-09-17 16:56:00.336493+00
B1301	Décoration d'espaces de vente et d'exposition	2024-09-17 16:56:00.3365+00
B1302	Décoration d'objets d'art et artisanaux	2024-09-17 16:56:00.336507+00
B1303	Gravure - ciselure	2024-09-17 16:56:00.336514+00
B1401	Réalisation d'objets en lianes, fibres et brins végétaux	2024-09-17 16:56:00.336521+00
B1402	Reliure et restauration de livres et archives	2024-09-17 16:56:00.336528+00
B1501	Fabrication et réparation d'instruments de musique	2024-09-17 16:56:00.336535+00
B1601	Métallerie d'art	2024-09-17 16:56:00.336542+00
B1602	Réalisation d'objets artistiques et fonctionnels en verre	2024-09-17 16:56:00.336549+00
B1603	Réalisation d'ouvrages en bijouterie, joaillerie et orfèvrerie	2024-09-17 16:56:00.336556+00
B1604	Réparation - montage en systèmes horlogers	2024-09-17 16:56:00.336563+00
B1701	Conservation et reconstitution d'espèces animales	2024-09-17 16:56:00.33657+00
B1801	Réalisation d'articles de chapellerie	2024-09-17 16:56:00.336577+00
B1802	Réalisation d'articles en cuir et matériaux souples (hors vêtement)	2024-09-17 16:56:00.336584+00
B1803	Réalisation de vêtements sur mesure ou en petite série	2024-09-17 16:56:00.336591+00
B1804	Réalisation d'ouvrages d'art en fils	2024-09-17 16:56:00.336597+00
B1805	Stylisme	2024-09-17 16:56:00.336604+00
B1806	Tapisserie - décoration en ameublement	2024-09-17 16:56:00.336611+00
C1101	Conception - développement produits d'assurances	2024-09-17 16:56:00.336618+00
C1102	Conseil clientèle en assurances	2024-09-17 16:56:00.336625+00
C1103	Courtage en assurances	2024-09-17 16:56:00.336632+00
C1104	Direction d'exploitation en assurances	2024-09-17 16:56:00.336639+00
C1105	Études actuarielles en assurances	2024-09-17 16:56:00.336646+00
C1106	Expertise risques en assurances	2024-09-17 16:56:00.336653+00
C1107	Indemnisations en assurances	2024-09-17 16:56:00.33666+00
C1108	Management de groupe et de service en assurances	2024-09-17 16:56:00.336667+00
C1109	Rédaction et gestion en assurances	2024-09-17 16:56:00.336673+00
C1110	Souscription d'assurances	2024-09-17 16:56:00.33668+00
C1201	Accueil et services bancaires	2024-09-17 16:56:00.336687+00
C1202	Analyse de crédits et risques bancaires	2024-09-17 16:56:00.336694+00
C1203	Relation clients banque/finance	2024-09-17 16:56:00.336701+00
C1204	Conception et expertise produits bancaires et financiers	2024-09-17 16:56:00.336708+00
C1205	Conseil en gestion de patrimoine financier	2024-09-17 16:56:00.336715+00
C1206	Gestion de clientèle bancaire	2024-09-17 16:56:00.336722+00
C1207	Management en exploitation bancaire	2024-09-17 16:56:00.336729+00
C1301	Front office marchés financiers	2024-09-17 16:56:00.336736+00
C1302	Gestion back et middle-office marchés financiers	2024-09-17 16:56:00.336743+00
C1303	Gestion de portefeuilles sur les marchés financiers	2024-09-17 16:56:00.33675+00
C1401	Gestion en banque et assurance	2024-09-17 16:56:00.336757+00
C1501	Gérance immobilière	2024-09-17 16:56:00.336763+00
C1502	Gestion locative immobilière	2024-09-17 16:56:00.33677+00
C1503	Management de projet immobilier	2024-09-17 16:56:00.336777+00
C1504	Transaction immobilière	2024-09-17 16:56:00.336783+00
D1101	Boucherie	2024-09-17 16:56:00.33679+00
D1102	Boulangerie - viennoiserie	2024-09-17 16:56:00.336797+00
D1103	Charcuterie - traiteur	2024-09-17 16:56:00.336804+00
D1104	Pâtisserie, confiserie, chocolaterie et glacerie	2024-09-17 16:56:00.336812+00
D1105	Poissonnerie	2024-09-17 16:56:00.336819+00
D1106	Vente en alimentation	2024-09-17 16:56:00.336826+00
D1107	Vente en gros de produits frais	2024-09-17 16:56:00.336833+00
D1201	Achat vente d'objets d'art, anciens ou d'occasion	2024-09-17 16:56:00.33684+00
D1202	Coiffure	2024-09-17 16:56:00.336846+00
D1203	Hydrothérapie	2024-09-17 16:56:00.336853+00
D1204	Location de véhicules ou de matériel de loisirs	2024-09-17 16:56:00.33686+00
D1205	Nettoyage d'articles textiles ou cuirs	2024-09-17 16:56:00.336867+00
D1206	Réparation d'articles en cuir et matériaux souples	2024-09-17 16:56:00.336874+00
D1207	Retouches en habillement	2024-09-17 16:56:00.336881+00
D1208	Soins esthétiques et corporels	2024-09-17 16:56:00.336888+00
D1209	Vente de végétaux	2024-09-17 16:56:00.336894+00
D1210	Vente en animalerie	2024-09-17 16:56:00.336901+00
D1211	Vente en articles de sport et loisirs	2024-09-17 16:56:00.336908+00
D1212	Vente en décoration et équipement du foyer	2024-09-17 16:56:00.336915+00
D1213	Vente en gros de matériel et équipement	2024-09-17 16:56:00.336922+00
D1214	Vente en habillement et accessoires de la personne	2024-09-17 16:56:00.336929+00
D1301	Management de magasin de détail	2024-09-17 16:56:00.336936+00
D1401	Assistanat commercial	2024-09-17 16:56:00.336943+00
D1402	Relation commerciale grands comptes et entreprises	2024-09-17 16:56:00.33695+00
D1403	Relation commerciale auprès de particuliers	2024-09-17 16:56:00.336957+00
D1404	Relation commerciale en vente de véhicules	2024-09-17 16:56:00.336964+00
D1405	Conseil en information médicale	2024-09-17 16:56:00.336977+00
D1406	Management en force de vente	2024-09-17 16:56:00.336984+00
D1407	Relation technico-commerciale	2024-09-17 16:56:00.336991+00
D1408	Téléconseil et télévente	2024-09-17 16:56:00.336998+00
D1501	Animation de vente	2024-09-17 16:56:00.337005+00
D1502	Management/gestion de rayon produits alimentaires	2024-09-17 16:56:00.337012+00
D1503	Management/gestion de rayon produits non alimentaires	2024-09-17 16:56:00.337019+00
D1504	Direction de magasin de grande distribution	2024-09-17 16:56:00.337025+00
D1505	Personnel de caisse	2024-09-17 16:56:00.337032+00
D1506	Marchandisage	2024-09-17 16:56:00.337039+00
D1507	Mise en rayon libre-service	2024-09-17 16:56:00.337046+00
D1508	Encadrement du personnel de caisses	2024-09-17 16:56:00.337053+00
D1509	Management de département en grande distribution	2024-09-17 16:56:00.33706+00
E1101	Animation de site multimédia	2024-09-17 16:56:00.337067+00
E1102	Ecriture d'ouvrages, de livres	2024-09-17 16:56:00.337074+00
E1103	Communication	2024-09-17 16:56:00.337081+00
E1104	Conception de contenus multimédias	2024-09-17 16:56:00.337089+00
E1105	Coordination d'édition	2024-09-17 16:56:00.337096+00
E1106	Journalisme et information média	2024-09-17 16:56:00.337103+00
E1107	Organisation d'évènementiel	2024-09-17 16:56:00.33711+00
E1108	Traduction, interprétariat	2024-09-17 16:56:00.337117+00
E1201	Photographie	2024-09-17 16:56:00.337124+00
E1202	Production en laboratoire cinématographique	2024-09-17 16:56:00.337131+00
E1203	Production en laboratoire photographique	2024-09-17 16:56:00.337138+00
E1204	Projection cinéma	2024-09-17 16:56:00.337144+00
E1205	Réalisation de contenus multimédias	2024-09-17 16:56:00.337151+00
E1301	Conduite de machines d'impression	2024-09-17 16:56:00.337158+00
E1302	Conduite de machines de façonnage routage	2024-09-17 16:56:00.337165+00
E1303	Encadrement des industries graphiques	2024-09-17 16:56:00.337172+00
E1304	Façonnage et routage	2024-09-17 16:56:00.33718+00
E1305	Préparation et correction en édition et presse	2024-09-17 16:56:00.337186+00
E1306	Prépresse	2024-09-17 16:56:00.337193+00
E1307	Reprographie	2024-09-17 16:56:00.337201+00
E1308	Intervention technique en industrie graphique	2024-09-17 16:56:00.337207+00
E1401	Développement et promotion publicitaire	2024-09-17 16:56:00.337214+00
E1402	Élaboration de plan média	2024-09-17 16:56:00.337221+00
F1101	Architecture du BTP et du paysage	2024-09-17 16:56:00.337228+00
F1102	Conception - aménagement d'espaces intérieurs	2024-09-17 16:56:00.337235+00
F1103	Contrôle et diagnostic technique du bâtiment	2024-09-17 16:56:00.337242+00
F1104	Dessin BTP et paysage	2024-09-17 16:56:00.337249+00
F1105	Études géologiques	2024-09-17 16:56:00.337256+00
F1106	Ingénierie et études du BTP	2024-09-17 16:56:00.337263+00
F1107	Mesures topographiques	2024-09-17 16:56:00.33727+00
F1108	Métré de la construction	2024-09-17 16:56:00.337277+00
F1201	Conduite de travaux du BTP et de travaux paysagers	2024-09-17 16:56:00.337284+00
F1202	Direction de chantier du BTP	2024-09-17 16:56:00.337291+00
F1203	Direction et ingénierie d'exploitation de gisements et de carrières	2024-09-17 16:56:00.337298+00
F1204	Qualité Sécurité Environnement et protection santé du BTP	2024-09-17 16:56:00.337305+00
F1301	Conduite de grue	2024-09-17 16:56:00.337311+00
F1302	Conduite d'engins de terrassement et de carrière	2024-09-17 16:56:00.337318+00
F1401	Extraction liquide et gazeuse	2024-09-17 16:56:00.337326+00
F1402	Extraction solide	2024-09-17 16:56:00.337333+00
F1501	Montage de structures et de charpentes bois	2024-09-17 16:56:00.337339+00
F1502	Montage de structures métalliques	2024-09-17 16:56:00.337346+00
F1503	Réalisation - installation d'ossatures bois	2024-09-17 16:56:00.337353+00
F1601	Application et décoration en plâtre, stuc et staff	2024-09-17 16:56:00.33736+00
F1602	Électricité bâtiment	2024-09-17 16:56:00.337367+00
F1603	Installation d'équipements sanitaires et thermiques	2024-09-17 16:56:00.337376+00
F1604	Montage d'agencements	2024-09-17 16:56:00.337383+00
F1605	Montage de réseaux électriques et télécoms	2024-09-17 16:56:00.33739+00
F1606	Peinture en bâtiment	2024-09-17 16:56:00.337397+00
F1607	Pose de fermetures menuisées	2024-09-17 16:56:00.337404+00
F1608	Pose de revêtements rigides	2024-09-17 16:56:00.337411+00
F1609	Pose de revêtements souples	2024-09-17 16:56:00.337418+00
F1610	Pose et restauration de couvertures	2024-09-17 16:56:00.337425+00
F1611	Réalisation et restauration de façades	2024-09-17 16:56:00.337432+00
F1612	Taille et décoration de pierres	2024-09-17 16:56:00.337439+00
F1613	Travaux d'étanchéité et d'isolation	2024-09-17 16:56:00.337446+00
F1701	Construction en béton	2024-09-17 16:56:00.337453+00
F1702	Construction de routes et voies	2024-09-17 16:56:00.337459+00
F1703	Maçonnerie	2024-09-17 16:56:00.337466+00
F1704	Préparation du gros oeuvre et des travaux publics	2024-09-17 16:56:00.337473+00
F1705	Pose de canalisations	2024-09-17 16:56:00.337481+00
F1706	Préfabrication en béton industriel	2024-09-17 16:56:00.337488+00
G1101	Accueil touristique	2024-09-17 16:56:00.337495+00
G1102	Promotion du tourisme local	2024-09-17 16:56:00.337502+00
G1201	Accompagnement de voyages, d'activités culturelles ou sportives	2024-09-17 16:56:00.337509+00
G1202	Animation d'activités culturelles ou ludiques	2024-09-17 16:56:00.337516+00
G1203	Animation de loisirs auprès d'enfants ou d'adolescents	2024-09-17 16:56:00.337523+00
G1204	Éducation en activités sportives	2024-09-17 16:56:00.33753+00
G1205	Personnel d'attractions ou de structures de loisirs	2024-09-17 16:56:00.337537+00
G1206	Personnel technique des jeux	2024-09-17 16:56:00.337544+00
G1301	Conception de produits touristiques	2024-09-17 16:56:00.33755+00
G1302	Optimisation de produits touristiques	2024-09-17 16:56:00.337557+00
G1303	Vente de voyages	2024-09-17 16:56:00.337564+00
G1401	Assistance de direction d'hôtel-restaurant	2024-09-17 16:56:00.337571+00
G1402	Management d'hôtel-restaurant	2024-09-17 16:56:00.337578+00
G1403	Gestion de structure de loisirs ou d'hébergement touristique	2024-09-17 16:56:00.337584+00
G1404	Management d'établissement de restauration collective	2024-09-17 16:56:00.337591+00
G1501	Personnel d'étage	2024-09-17 16:56:00.337598+00
G1502	Personnel polyvalent d'hôtellerie	2024-09-17 16:56:00.337605+00
G1503	Management du personnel d'étage	2024-09-17 16:56:00.337612+00
G1601	Management du personnel de cuisine	2024-09-17 16:56:00.337619+00
G1602	Personnel de cuisine	2024-09-17 16:56:00.337626+00
G1603	Personnel polyvalent en restauration	2024-09-17 16:56:00.337632+00
G1604	Fabrication de crêpes ou pizzas	2024-09-17 16:56:00.337639+00
G1605	Plonge en restauration	2024-09-17 16:56:00.337646+00
G1701	Conciergerie en hôtellerie	2024-09-17 16:56:00.337653+00
G1702	Personnel du hall	2024-09-17 16:56:00.33766+00
G1703	Réception en hôtellerie	2024-09-17 16:56:00.337667+00
G1801	Café, bar brasserie	2024-09-17 16:56:00.337673+00
G1802	Management du service en restauration	2024-09-17 16:56:00.33768+00
G1803	Service en restauration	2024-09-17 16:56:00.337687+00
G1804	Sommellerie	2024-09-17 16:56:00.337694+00
H1101	Assistance et support technique client	2024-09-17 16:56:00.337701+00
H1102	Management et ingénierie d'affaires	2024-09-17 16:56:00.337709+00
H1201	Expertise technique couleur en industrie	2024-09-17 16:56:00.337716+00
H1202	Conception et dessin de produits électriques et électroniques	2024-09-17 16:56:00.337723+00
H1203	Conception et dessin produits mécaniques	2024-09-17 16:56:00.337729+00
H1204	Design industriel	2024-09-17 16:56:00.337736+00
H1205	Études - modèles en industrie des matériaux souples	2024-09-17 16:56:00.337743+00
H1206	Management et ingénierie études, recherche et développement industriel	2024-09-17 16:56:00.33775+00
H1207	Rédaction technique	2024-09-17 16:56:00.337757+00
H1208	Intervention technique en études et conception en automatisme	2024-09-17 16:56:00.337764+00
H1209	Intervention technique en études et développement électronique	2024-09-17 16:56:00.33777+00
H1210	Intervention technique en études, recherche et développement	2024-09-17 16:56:00.337777+00
H1301	Inspection de conformité	2024-09-17 16:56:00.337784+00
H1302	Management et ingénierie Hygiène Sécurité Environnement -HSE- industriels	2024-09-17 16:56:00.337791+00
H1303	Intervention technique en Hygiène Sécurité Environnement -HSE- industriel	2024-09-17 16:56:00.337798+00
H1401	Management et ingénierie gestion industrielle et logistique	2024-09-17 16:56:00.337805+00
H1402	Management et ingénierie méthodes et industrialisation	2024-09-17 16:56:00.337811+00
H1403	Intervention technique en gestion industrielle et logistique	2024-09-17 16:56:00.337818+00
H1404	Intervention technique en méthodes et industrialisation	2024-09-17 16:56:00.337825+00
H1501	Direction de laboratoire d'analyse industrielle	2024-09-17 16:56:00.337832+00
H1502	Management et ingénierie qualité industrielle	2024-09-17 16:56:00.337839+00
H1503	Intervention technique en laboratoire d'analyse industrielle	2024-09-17 16:56:00.337846+00
H1504	Intervention technique en contrôle essai qualité en électricité et électronique	2024-09-17 16:56:00.337853+00
H1505	Intervention technique en formulation et analyse sensorielle	2024-09-17 16:56:00.337859+00
H1506	Intervention technique qualité en mécanique et travail des métaux	2024-09-17 16:56:00.337866+00
H2101	Abattage et découpe des viandes	2024-09-17 16:56:00.337873+00
H2102	Conduite d'équipement de production alimentaire	2024-09-17 16:56:00.33788+00
H2201	Assemblage d'ouvrages en bois	2024-09-17 16:56:00.337887+00
H2202	Conduite d'équipement de fabrication de l'ameublement et du bois	2024-09-17 16:56:00.337894+00
H2203	Conduite d'installation de production de panneaux bois	2024-09-17 16:56:00.337901+00
H2204	Encadrement des industries de l'ameublement et du bois	2024-09-17 16:56:00.337908+00
H2205	Première transformation de bois d'oeuvre	2024-09-17 16:56:00.337915+00
H2206	Réalisation de menuiserie bois et tonnellerie	2024-09-17 16:56:00.337922+00
H2207	Réalisation de meubles en bois	2024-09-17 16:56:00.337929+00
H2208	Réalisation d'ouvrages décoratifs en bois	2024-09-17 16:56:00.337936+00
H2209	Intervention technique en ameublement et bois	2024-09-17 16:56:00.337943+00
H2301	Conduite d'équipement de production chimique ou pharmaceutique	2024-09-17 16:56:00.33795+00
H2401	Assemblage - montage d'articles en cuirs, peaux	2024-09-17 16:56:00.337957+00
H2402	Assemblage - montage de vêtements et produits textiles	2024-09-17 16:56:00.337964+00
H2403	Conduite de machine de fabrication de produits textiles	2024-09-17 16:56:00.337971+00
H2404	Conduite de machine de production et transformation des fils	2024-09-17 16:56:00.337978+00
H2405	Conduite de machine de textiles nontissés	2024-09-17 16:56:00.337985+00
H2406	Conduite de machine de traitement textile	2024-09-17 16:56:00.337992+00
H2407	Conduite de machine de transformation et de finition des cuirs et peaux	2024-09-17 16:56:00.338+00
H2408	Conduite de machine d'impression textile	2024-09-17 16:56:00.338007+00
H2409	Coupe cuir, textile et matériaux souples	2024-09-17 16:56:00.338014+00
H2410	Mise en forme, repassage et finitions en industrie textile	2024-09-17 16:56:00.338021+00
H2411	Montage de prototype cuir et matériaux souples	2024-09-17 16:56:00.338028+00
H2412	Patronnage - gradation	2024-09-17 16:56:00.338035+00
H2413	Préparation de fils, montage de métiers textiles	2024-09-17 16:56:00.338042+00
H2414	Préparation et finition d'articles en cuir et matériaux souples	2024-09-17 16:56:00.338048+00
H2415	Contrôle en industrie du cuir et du textile	2024-09-17 16:56:00.338055+00
H2501	Encadrement de production de matériel électrique et électronique	2024-09-17 16:56:00.338062+00
H2502	Management et ingénierie de production	2024-09-17 16:56:00.338069+00
H2503	Pilotage d'unité élémentaire de production mécanique ou de travail des métaux	2024-09-17 16:56:00.338076+00
H2504	Encadrement d'équipe en industrie de transformation	2024-09-17 16:56:00.338083+00
H2505	Encadrement d'équipe ou d'atelier en matériaux souples	2024-09-17 16:56:00.33809+00
H2601	Bobinage électrique	2024-09-17 16:56:00.338097+00
H2602	Câblage électrique et électromécanique	2024-09-17 16:56:00.338104+00
H2603	Conduite d'installation automatisée de production électrique, électronique et microélectronique	2024-09-17 16:56:00.33811+00
H2604	Montage de produits électriques et électroniques	2024-09-17 16:56:00.338117+00
H2605	Montage et câblage électronique	2024-09-17 16:56:00.338124+00
H2701	Pilotage d'installation énergétique et pétrochimique	2024-09-17 16:56:00.338131+00
H2801	Conduite d'équipement de transformation du verre	2024-09-17 16:56:00.338138+00
H2802	Conduite d'installation de production de matériaux de construction	2024-09-17 16:56:00.338145+00
H2803	Façonnage et émaillage en industrie céramique	2024-09-17 16:56:00.338152+00
H2804	Pilotage de centrale à béton prêt à l'emploi, ciment, enrobés et granulats	2024-09-17 16:56:00.338159+00
H2805	Pilotage d'installation de production verrière	2024-09-17 16:56:00.338166+00
H2901	Ajustement et montage de fabrication	2024-09-17 16:56:00.338173+00
H2902	Chaudronnerie - tôlerie	2024-09-17 16:56:00.33818+00
H2903	Conduite d'équipement d'usinage	2024-09-17 16:56:00.338187+00
H2904	Conduite d'équipement de déformation des métaux	2024-09-17 16:56:00.338194+00
H2905	Conduite d'équipement de formage et découpage des matériaux	2024-09-17 16:56:00.338201+00
H2906	Conduite d'installation automatisée ou robotisée de fabrication mécanique	2024-09-17 16:56:00.338208+00
H2907	Conduite d'installation de production des métaux	2024-09-17 16:56:00.338215+00
H2908	Modelage de matériaux non métalliques	2024-09-17 16:56:00.338222+00
H2909	Montage-assemblage mécanique	2024-09-17 16:56:00.338229+00
H2910	Moulage sable	2024-09-17 16:56:00.338236+00
H2911	Réalisation de structures métalliques	2024-09-17 16:56:00.338243+00
H2912	Réglage d'équipement de production industrielle	2024-09-17 16:56:00.33825+00
H2913	Soudage manuel	2024-09-17 16:56:00.338257+00
H2914	Réalisation et montage en tuyauterie	2024-09-17 16:56:00.338264+00
H3101	Conduite d'équipement de fabrication de papier ou de carton	2024-09-17 16:56:00.338271+00
H3102	Conduite d'installation de pâte à papier	2024-09-17 16:56:00.338278+00
H3201	Conduite d'équipement de formage des plastiques et caoutchoucs	2024-09-17 16:56:00.338286+00
H3202	Réglage d'équipement de formage des plastiques et caoutchoucs	2024-09-17 16:56:00.338293+00
H3203	Fabrication de pièces en matériaux composites	2024-09-17 16:56:00.3383+00
H3301	Conduite d'équipement de conditionnement	2024-09-17 16:56:00.338307+00
H3302	Opérations manuelles d'assemblage, tri ou emballage	2024-09-17 16:56:00.338314+00
H3303	Préparation de matières et produits industriels (broyage, mélange, ...)	2024-09-17 16:56:00.338321+00
H3401	Conduite de traitement d'abrasion de surface	2024-09-17 16:56:00.338328+00
H3402	Conduite de traitement par dépôt de surface	2024-09-17 16:56:00.338335+00
H3403	Conduite de traitement thermique	2024-09-17 16:56:00.338342+00
H3404	Peinture industrielle	2024-09-17 16:56:00.338349+00
I1101	Direction et ingénierie en entretien infrastructure et bâti	2024-09-17 16:56:00.338356+00
I1102	Management et ingénierie de maintenance industrielle	2024-09-17 16:56:00.338364+00
I1103	Supervision d'entretien et gestion de véhicules	2024-09-17 16:56:00.338371+00
I1201	Entretien d'affichage et mobilier urbain	2024-09-17 16:56:00.338378+00
I1202	Entretien et surveillance du tracé routier	2024-09-17 16:56:00.338385+00
I1203	Maintenance des bâtiments et des locaux	2024-09-17 16:56:00.338392+00
I1301	Installation et maintenance d'ascenseurs	2024-09-17 16:56:00.338399+00
I1302	Installation et maintenance d'automatismes	2024-09-17 16:56:00.338406+00
I1303	Installation et maintenance de distributeurs automatiques	2024-09-17 16:56:00.338413+00
I1304	Installation et maintenance d'équipements industriels et d'exploitation	2024-09-17 16:56:00.33842+00
I1305	Installation et maintenance électronique	2024-09-17 16:56:00.338428+00
I1306	Installation et maintenance en froid, conditionnement d'air	2024-09-17 16:56:00.338435+00
I1307	Installation et maintenance télécoms et courants faibles	2024-09-17 16:56:00.338442+00
I1308	Maintenance d'installation de chauffage	2024-09-17 16:56:00.338449+00
I1309	Maintenance électrique	2024-09-17 16:56:00.338456+00
I1310	Maintenance mécanique industrielle	2024-09-17 16:56:00.338463+00
I1401	Maintenance informatique et bureautique	2024-09-17 16:56:00.33847+00
I1402	Réparation de biens électrodomestiques et multimédia	2024-09-17 16:56:00.338477+00
I1501	Intervention en grande hauteur	2024-09-17 16:56:00.338484+00
I1502	Intervention en milieu subaquatique	2024-09-17 16:56:00.338491+00
I1503	Intervention en milieux et produits nocifs	2024-09-17 16:56:00.338498+00
I1601	Installation et maintenance en nautisme	2024-09-17 16:56:00.338505+00
I1602	Maintenance d'aéronefs	2024-09-17 16:56:00.338512+00
I1603	Maintenance d'engins de chantier, levage, manutention et de machines agricoles	2024-09-17 16:56:00.338519+00
I1604	Mécanique automobile et entretien de véhicules	2024-09-17 16:56:00.338527+00
I1605	Mécanique de marine	2024-09-17 16:56:00.338534+00
I1606	Réparation de carrosserie	2024-09-17 16:56:00.338541+00
I1607	Réparation de cycles, motocycles et motoculteurs de loisirs	2024-09-17 16:56:00.338548+00
J1101	Médecine de prévention	2024-09-17 16:56:00.338555+00
J1102	Médecine généraliste et spécialisée	2024-09-17 16:56:00.338564+00
J1103	Médecine dentaire	2024-09-17 16:56:00.338571+00
J1104	Suivi de la grossesse et de l'accouchement	2024-09-17 16:56:00.338578+00
J1201	Biologie médicale	2024-09-17 16:56:00.338585+00
J1202	Pharmacie	2024-09-17 16:56:00.338593+00
J1301	Personnel polyvalent des services hospitaliers	2024-09-17 16:56:00.3386+00
J1302	Analyses médicales	2024-09-17 16:56:00.338607+00
J1303	Assistance médico-technique	2024-09-17 16:56:00.338614+00
J1304	Aide en puériculture	2024-09-17 16:56:00.338621+00
J1305	Conduite de véhicules sanitaires	2024-09-17 16:56:00.338628+00
J1306	Imagerie médicale	2024-09-17 16:56:00.338635+00
J1307	Préparation en pharmacie	2024-09-17 16:56:00.338642+00
J1401	Audioprothèses	2024-09-17 16:56:00.338649+00
J1402	Diététique	2024-09-17 16:56:00.338656+00
J1403	Ergothérapie	2024-09-17 16:56:00.338663+00
J1404	Kinésithérapie	2024-09-17 16:56:00.33867+00
J1405	Optique - lunetterie	2024-09-17 16:56:00.338677+00
J1406	Orthophonie	2024-09-17 16:56:00.338684+00
J1407	Orthoptique	2024-09-17 16:56:00.338691+00
J1408	Ostéopathie et chiropraxie	2024-09-17 16:56:00.338698+00
J1409	Pédicurie et podologie	2024-09-17 16:56:00.338705+00
J1410	Prothèses dentaires	2024-09-17 16:56:00.338712+00
J1411	Prothèses et orthèses	2024-09-17 16:56:00.338719+00
J1412	Rééducation en psychomotricité	2024-09-17 16:56:00.338726+00
J1501	Soins d'hygiène, de confort du patient	2024-09-17 16:56:00.338733+00
J1502	Coordination de services médicaux ou paramédicaux	2024-09-17 16:56:00.33874+00
J1503	Soins infirmiers spécialisés en anesthésie	2024-09-17 16:56:00.338747+00
J1504	Soins infirmiers spécialisés en bloc opératoire	2024-09-17 16:56:00.338754+00
J1505	Soins infirmiers spécialisés en prévention	2024-09-17 16:56:00.338761+00
J1506	Soins infirmiers généralistes	2024-09-17 16:56:00.338769+00
J1507	Soins infirmiers spécialisés en puériculture	2024-09-17 16:56:00.338776+00
K1101	Accompagnement et médiation familiale	2024-09-17 16:56:00.338783+00
K1102	Aide aux bénéficiaires d'une mesure de protection juridique	2024-09-17 16:56:00.33879+00
K1103	Développement personnel et bien-être de la personne	2024-09-17 16:56:00.338797+00
K1104	Psychologie	2024-09-17 16:56:00.338804+00
K1201	Action sociale	2024-09-17 16:56:00.338811+00
K1202	Éducation de jeunes enfants	2024-09-17 16:56:00.338818+00
K1203	Encadrement technique en insertion professionnelle	2024-09-17 16:56:00.338825+00
K1204	Médiation sociale et facilitation de la vie en société	2024-09-17 16:56:00.338832+00
K1205	Information sociale	2024-09-17 16:56:00.338839+00
K1206	Intervention socioculturelle	2024-09-17 16:56:00.338846+00
K1207	Intervention socioéducative	2024-09-17 16:56:00.338853+00
K1301	Accompagnement médicosocial	2024-09-17 16:56:00.33886+00
K1302	Assistance auprès d'adultes	2024-09-17 16:56:00.338867+00
K1303	Assistance auprès d'enfants	2024-09-17 16:56:00.338874+00
K1304	Services domestiques	2024-09-17 16:56:00.338881+00
K1305	Intervention sociale et familiale	2024-09-17 16:56:00.338889+00
K1401	Conception et pilotage de la politique des pouvoirs publics	2024-09-17 16:56:00.338896+00
K1402	Conseil en Santé Publique	2024-09-17 16:56:00.338903+00
K1403	Management de structure de santé, sociale ou pénitentiaire	2024-09-17 16:56:00.33891+00
K1404	Mise en oeuvre et pilotage de la politique des pouvoirs publics	2024-09-17 16:56:00.338917+00
K1405	Représentation de l'Etat sur le territoire national ou international	2024-09-17 16:56:00.338924+00
K1501	Application des règles financières publiques	2024-09-17 16:56:00.338931+00
K1502	Contrôle et inspection des Affaires Sociales	2024-09-17 16:56:00.338938+00
K1503	Contrôle et inspection des impôts	2024-09-17 16:56:00.338945+00
K1504	Contrôle et inspection du Trésor Public	2024-09-17 16:56:00.338952+00
K1505	Protection des consommateurs et contrôle des échanges commerciaux	2024-09-17 16:56:00.338959+00
K1601	Gestion de l'information et de la documentation	2024-09-17 16:56:00.338966+00
K1602	Gestion de patrimoine culturel	2024-09-17 16:56:00.338973+00
K1701	Personnel de la Défense	2024-09-17 16:56:00.33898+00
K1702	Direction de la sécurité civile et des secours	2024-09-17 16:56:00.338988+00
K1703	Direction opérationnelle de la défense	2024-09-17 16:56:00.338995+00
K1704	Management de la sécurité publique	2024-09-17 16:56:00.339002+00
K1705	Sécurité civile et secours	2024-09-17 16:56:00.339009+00
K1706	Sécurité publique	2024-09-17 16:56:00.339016+00
K1707	Surveillance municipale	2024-09-17 16:56:00.339023+00
K1801	Conseil en emploi et insertion socioprofessionnelle	2024-09-17 16:56:00.339031+00
K1802	Développement local	2024-09-17 16:56:00.339038+00
K1901	Aide et médiation judiciaire	2024-09-17 16:56:00.339045+00
K1902	Collaboration juridique	2024-09-17 16:56:00.339052+00
K1903	Défense et conseil juridique	2024-09-17 16:56:00.339059+00
K1904	Magistrature	2024-09-17 16:56:00.339066+00
K2101	Conseil en formation	2024-09-17 16:56:00.339073+00
K2102	Coordination pédagogique	2024-09-17 16:56:00.33908+00
K2103	Direction d'établissement et d'enseignement	2024-09-17 16:56:00.339088+00
K2104	Éducation et surveillance au sein d'établissements d'enseignement	2024-09-17 16:56:00.339095+00
K2105	Enseignement artistique	2024-09-17 16:56:00.339102+00
K2106	Enseignement des écoles	2024-09-17 16:56:00.339109+00
K2107	Enseignement général du second degré	2024-09-17 16:56:00.339116+00
K2108	Enseignement supérieur	2024-09-17 16:56:00.339123+00
K2109	Enseignement technique et professionnel	2024-09-17 16:56:00.33913+00
K2110	Formation en conduite de véhicules	2024-09-17 16:56:00.339137+00
K2111	Formation professionnelle	2024-09-17 16:56:00.339144+00
K2112	Orientation scolaire et professionnelle	2024-09-17 16:56:00.339151+00
K2201	Blanchisserie industrielle	2024-09-17 16:56:00.339158+00
K2202	Lavage de vitres	2024-09-17 16:56:00.339165+00
K2203	Management et inspection en propreté de locaux	2024-09-17 16:56:00.339172+00
K2204	Nettoyage de locaux	2024-09-17 16:56:00.339179+00
K2301	Distribution et assainissement d'eau	2024-09-17 16:56:00.339186+00
K2302	Management et inspection en environnement urbain	2024-09-17 16:56:00.339193+00
K2303	Nettoyage des espaces urbains	2024-09-17 16:56:00.3392+00
K2304	Revalorisation de produits industriels	2024-09-17 16:56:00.339207+00
K2305	Salubrité et traitement de nuisibles	2024-09-17 16:56:00.339214+00
K2306	Supervision d'exploitation éco-industrielle	2024-09-17 16:56:00.339221+00
K2401	Recherche en sciences de l'homme et de la société	2024-09-17 16:56:00.339228+00
K2402	Recherche en sciences de l'univers, de la matière et du vivant	2024-09-17 16:56:00.339235+00
K2501	Gardiennage de locaux	2024-09-17 16:56:00.339242+00
K2502	Management de sécurité privée	2024-09-17 16:56:00.339249+00
K2503	Sécurité et surveillance privées	2024-09-17 16:56:00.339256+00
K2601	Conduite d'opérations funéraires	2024-09-17 16:56:00.339263+00
K2602	Conseil en services funéraires	2024-09-17 16:56:00.33927+00
K2603	Thanatopraxie	2024-09-17 16:56:00.339277+00
L1101	Animation musicale et scénique	2024-09-17 16:56:00.339284+00
L1102	Mannequinat et pose artistique	2024-09-17 16:56:00.339291+00
L1103	Présentation de spectacles ou d'émissions	2024-09-17 16:56:00.339298+00
L1201	Danse	2024-09-17 16:56:00.339305+00
L1202	Musique et chant	2024-09-17 16:56:00.339312+00
L1203	Art dramatique	2024-09-17 16:56:00.339319+00
L1204	Arts du cirque et arts visuels	2024-09-17 16:56:00.339326+00
L1301	Mise en scène de spectacles vivants	2024-09-17 16:56:00.339332+00
L1302	Production et administration spectacle, cinéma et audiovisuel	2024-09-17 16:56:00.339339+00
L1303	Promotion d'artistes et de spectacles	2024-09-17 16:56:00.339346+00
L1304	Réalisation cinématographique et audiovisuelle	2024-09-17 16:56:00.339353+00
L1401	Sportif professionnel	2024-09-17 16:56:00.33936+00
L1501	Coiffure et maquillage spectacle	2024-09-17 16:56:00.339367+00
L1502	Costume et habillage spectacle	2024-09-17 16:56:00.339374+00
L1503	Décor et accessoires spectacle	2024-09-17 16:56:00.339382+00
L1504	Éclairage spectacle	2024-09-17 16:56:00.339389+00
L1505	Image cinématographique et télévisuelle	2024-09-17 16:56:00.339396+00
L1506	Machinerie spectacle	2024-09-17 16:56:00.339402+00
L1507	Montage audiovisuel et post-production	2024-09-17 16:56:00.339409+00
L1508	Prise de son et sonorisation	2024-09-17 16:56:00.339416+00
L1509	Régie générale	2024-09-17 16:56:00.339423+00
L1510	Films d'animation et effets spéciaux	2024-09-17 16:56:00.33943+00
M1101	Achats	2024-09-17 16:56:00.339437+00
M1102	Direction des achats	2024-09-17 16:56:00.339444+00
M1201	Analyse et ingénierie financière	2024-09-17 16:56:00.339451+00
M1202	Audit et contrôle comptables et financiers	2024-09-17 16:56:00.339458+00
M1203	Comptabilité	2024-09-17 16:56:00.339466+00
M1204	Contrôle de gestion	2024-09-17 16:56:00.339473+00
M1205	Direction administrative et financière	2024-09-17 16:56:00.33948+00
M1206	Management de groupe ou de service comptable	2024-09-17 16:56:00.339487+00
M1207	Trésorerie et financement	2024-09-17 16:56:00.339494+00
M1301	Direction de grande entreprise ou d'établissement public	2024-09-17 16:56:00.339501+00
M1302	Direction de petite ou moyenne entreprise	2024-09-17 16:56:00.339508+00
M1401	Conduite d'enquêtes	2024-09-17 16:56:00.339515+00
M1402	Conseil en organisation et management d'entreprise	2024-09-17 16:56:00.339522+00
M1403	Études et prospectives socio-économiques	2024-09-17 16:56:00.339529+00
M1404	Management et gestion d'enquêtes	2024-09-17 16:56:00.339536+00
M1501	Assistanat en ressources humaines	2024-09-17 16:56:00.339543+00
M1502	Développement des ressources humaines	2024-09-17 16:56:00.33955+00
M1503	Management des ressources humaines	2024-09-17 16:56:00.339557+00
M1601	Accueil et renseignements	2024-09-17 16:56:00.339564+00
M1602	Opérations administratives	2024-09-17 16:56:00.339571+00
M1603	Distribution de documents	2024-09-17 16:56:00.339578+00
M1604	Assistanat de direction	2024-09-17 16:56:00.339585+00
M1605	Assistanat technique et administratif	2024-09-17 16:56:00.339592+00
M1606	Saisie de données	2024-09-17 16:56:00.339599+00
M1607	Secrétariat	2024-09-17 16:56:00.339606+00
M1608	Secrétariat comptable	2024-09-17 16:56:00.339613+00
M1609	Secrétariat et assistanat médical ou médico-social	2024-09-17 16:56:00.33962+00
M1701	Administration des ventes	2024-09-17 16:56:00.339627+00
M1702	Analyse de tendance	2024-09-17 16:56:00.339634+00
M1703	Management et gestion de produit	2024-09-17 16:56:00.339641+00
M1704	Management relation clientèle	2024-09-17 16:56:00.339648+00
M1705	Marketing	2024-09-17 16:56:00.339655+00
M1706	Promotion des ventes	2024-09-17 16:56:00.339662+00
M1707	Stratégie commerciale	2024-09-17 16:56:00.339669+00
M1801	Administration de systèmes d'information	2024-09-17 16:56:00.339676+00
M1802	Expertise et support en systèmes d'information	2024-09-17 16:56:00.339683+00
M1803	Direction des systèmes d'information	2024-09-17 16:56:00.33969+00
M1804	Études et développement de réseaux de télécoms	2024-09-17 16:56:00.339697+00
M1805	Études et développement informatique	2024-09-17 16:56:00.339704+00
M1806	Conseil et maîtrise d'ouvrage en systèmes d'information	2024-09-17 16:56:00.339711+00
M1807	Exploitation de systèmes de communication et de commandement	2024-09-17 16:56:00.339718+00
M1808	Information géographique	2024-09-17 16:56:00.339725+00
M1809	Information météorologique	2024-09-17 16:56:00.339732+00
M1810	Production et exploitation de systèmes d'information	2024-09-17 16:56:00.339739+00
N1101	Conduite d'engins de déplacement des charges	2024-09-17 16:56:00.339746+00
N1102	Déménagement	2024-09-17 16:56:00.339753+00
N1103	Magasinage et préparation de commandes	2024-09-17 16:56:00.33976+00
N1104	Manoeuvre et conduite d'engins lourds de manutention	2024-09-17 16:56:00.339767+00
N1105	Manutention manuelle de charges	2024-09-17 16:56:00.339774+00
N1201	Affrètement transport	2024-09-17 16:56:00.339781+00
N1202	Gestion des opérations de circulation internationale des marchandises	2024-09-17 16:56:00.339788+00
N1301	Conception et organisation de la chaîne logistique	2024-09-17 16:56:00.339795+00
N1302	Direction de site logistique	2024-09-17 16:56:00.339802+00
N1303	Intervention technique d'exploitation logistique	2024-09-17 16:56:00.339809+00
N2101	Navigation commerciale aérienne	2024-09-17 16:56:00.339816+00
N2102	Pilotage et navigation technique aérienne	2024-09-17 16:56:00.339823+00
N2201	Personnel d'escale aéroportuaire	2024-09-17 16:56:00.33983+00
N2202	Contrôle de la navigation aérienne	2024-09-17 16:56:00.339837+00
N2203	Exploitation des pistes aéroportuaires	2024-09-17 16:56:00.339844+00
N2204	Préparation des vols	2024-09-17 16:56:00.339851+00
N2205	Direction d'escale et exploitation aéroportuaire	2024-09-17 16:56:00.339858+00
N3101	Encadrement de la navigation maritime	2024-09-17 16:56:00.339866+00
N3102	Equipage de la navigation maritime	2024-09-17 16:56:00.339873+00
N3103	Navigation fluviale	2024-09-17 16:56:00.33988+00
N3201	Exploitation des opérations portuaires et du transport maritime	2024-09-17 16:56:00.339887+00
N3202	Exploitation du transport fluvial	2024-09-17 16:56:00.339894+00
N3203	Manutention portuaire	2024-09-17 16:56:00.339901+00
N4101	Conduite de transport de marchandises sur longue distance	2024-09-17 16:56:00.339908+00
N4102	Conduite de transport de particuliers	2024-09-17 16:56:00.339915+00
N4103	Conduite de transport en commun sur route	2024-09-17 16:56:00.339922+00
N4104	Courses et livraisons express	2024-09-17 16:56:00.339929+00
N4105	Conduite et livraison par tournées sur courte distance	2024-09-17 16:56:00.339936+00
N4201	Direction d'exploitation des transports routiers de marchandises	2024-09-17 16:56:00.339943+00
N4202	Direction d'exploitation des transports routiers de personnes	2024-09-17 16:56:00.33995+00
N4203	Intervention technique d'exploitation des transports routiers de marchandises	2024-09-17 16:56:00.339957+00
N4204	Intervention technique d'exploitation des transports routiers de personnes	2024-09-17 16:56:00.339964+00
N4301	Conduite sur rails	2024-09-17 16:56:00.339971+00
N4302	Contrôle des transports en commun	2024-09-17 16:56:00.339978+00
N4401	Circulation du réseau ferré	2024-09-17 16:56:00.339985+00
N4402	Exploitation et manoeuvre des remontées mécaniques	2024-09-17 16:56:00.339992+00
N4403	Manoeuvre du réseau ferré	2024-09-17 16:56:00.339999+00
\.


--
-- PostgreSQL database dump complete
--

