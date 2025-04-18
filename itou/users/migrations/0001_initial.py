# Generated by Django 5.0.3 on 2024-03-22 10:10
import uuid

import citext
import django.contrib.auth.validators
import django.contrib.gis.db.models.fields
import django.contrib.postgres.fields.citext
import django.contrib.postgres.indexes
import django.core.serializers.json
import django.core.validators
import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import itou.users.models
import itou.utils.models
import itou.utils.validators


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("asp", "0001_initial"),
        ("asp", "__first__"),
        ("auth", "0011_update_proxy_permissions"),
        ("cities", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                (
                    "is_superuser",
                    models.BooleanField(
                        default=False,
                        help_text="Designates that this user has all permissions without explicitly assigning them.",
                        verbose_name="superuser status",
                    ),
                ),
                (
                    "username",
                    models.CharField(
                        error_messages={"unique": "A user with that username already exists."},
                        help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.",
                        max_length=150,
                        unique=True,
                        validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                        verbose_name="username",
                    ),
                ),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                (
                    "email",
                    citext.CIEmailField(
                        db_index=True, max_length=254, null=True, unique=True, verbose_name="adresse e-mail"
                    ),
                ),
                (
                    "is_staff",
                    models.BooleanField(
                        default=False,
                        help_text="Designates whether the user can log into this admin site.",
                        verbose_name="staff status",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Designates whether this user should be treated as active. Unselect this instead of "
                        "deleting accounts.",
                        verbose_name="active",
                    ),
                ),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date joined")),
                (
                    "birthdate",
                    models.DateField(
                        blank=True,
                        null=True,
                        validators=[itou.utils.validators.validate_birthdate],
                        verbose_name="date de naissance",
                    ),
                ),
                ("phone", models.CharField(blank=True, max_length=20, verbose_name="téléphone")),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        help_text="The groups this user belongs to. A user will get all permissions granted to each "
                        "of their groups.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.group",
                        verbose_name="groups",
                    ),
                ),
                (
                    "user_permissions",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Specific permissions for this user.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.permission",
                        verbose_name="user permissions",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="créé par",
                    ),
                ),
                ("address_line_1", models.CharField(blank=True, max_length=255, verbose_name="adresse")),
                (
                    "address_line_2",
                    models.CharField(
                        blank=True,
                        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
                        max_length=255,
                        verbose_name="complément d'adresse",
                    ),
                ),
                ("city", models.CharField(blank=True, max_length=255, verbose_name="ville")),
                (
                    "coords",
                    django.contrib.gis.db.models.fields.PointField(blank=True, geography=True, null=True, srid=4326),
                ),
                (
                    "department",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "01 - Ain"),
                            ("02", "02 - Aisne"),
                            ("03", "03 - Allier"),
                            ("04", "04 - Alpes-de-Haute-Provence"),
                            ("05", "05 - Hautes-Alpes"),
                            ("06", "06 - Alpes-Maritimes"),
                            ("07", "07 - Ardèche"),
                            ("08", "08 - Ardennes"),
                            ("09", "09 - Ariège"),
                            ("10", "10 - Aube"),
                            ("11", "11 - Aude"),
                            ("12", "12 - Aveyron"),
                            ("13", "13 - Bouches-du-Rhône"),
                            ("14", "14 - Calvados"),
                            ("15", "15 - Cantal"),
                            ("16", "16 - Charente"),
                            ("17", "17 - Charente-Maritime"),
                            ("18", "18 - Cher"),
                            ("19", "19 - Corrèze"),
                            ("2A", "2A - Corse-du-Sud"),
                            ("2B", "2B - Haute-Corse"),
                            ("21", "21 - Côte-d'Or"),
                            ("22", "22 - Côtes-d'Armor"),
                            ("23", "23 - Creuse"),
                            ("24", "24 - Dordogne"),
                            ("25", "25 - Doubs"),
                            ("26", "26 - Drôme"),
                            ("27", "27 - Eure"),
                            ("28", "28 - Eure-et-Loir"),
                            ("29", "29 - Finistère"),
                            ("30", "30 - Gard"),
                            ("31", "31 - Haute-Garonne"),
                            ("32", "32 - Gers"),
                            ("33", "33 - Gironde"),
                            ("34", "34 - Hérault"),
                            ("35", "35 - Ille-et-Vilaine"),
                            ("36", "36 - Indre"),
                            ("37", "37 - Indre-et-Loire"),
                            ("38", "38 - Isère"),
                            ("39", "39 - Jura"),
                            ("40", "40 - Landes"),
                            ("41", "41 - Loir-et-Cher"),
                            ("42", "42 - Loire"),
                            ("43", "43 - Haute-Loire"),
                            ("44", "44 - Loire-Atlantique"),
                            ("45", "45 - Loiret"),
                            ("46", "46 - Lot"),
                            ("47", "47 - Lot-et-Garonne"),
                            ("48", "48 - Lozère"),
                            ("49", "49 - Maine-et-Loire"),
                            ("50", "50 - Manche"),
                            ("51", "51 - Marne"),
                            ("52", "52 - Haute-Marne"),
                            ("53", "53 - Mayenne"),
                            ("54", "54 - Meurthe-et-Moselle"),
                            ("55", "55 - Meuse"),
                            ("56", "56 - Morbihan"),
                            ("57", "57 - Moselle"),
                            ("58", "58 - Nièvre"),
                            ("59", "59 - Nord"),
                            ("60", "60 - Oise"),
                            ("61", "61 - Orne"),
                            ("62", "62 - Pas-de-Calais"),
                            ("63", "63 - Puy-de-Dôme"),
                            ("64", "64 - Pyrénées-Atlantiques"),
                            ("65", "65 - Hautes-Pyrénées"),
                            ("66", "66 - Pyrénées-Orientales"),
                            ("67", "67 - Bas-Rhin"),
                            ("68", "68 - Haut-Rhin"),
                            ("69", "69 - Rhône"),
                            ("70", "70 - Haute-Saône"),
                            ("71", "71 - Saône-et-Loire"),
                            ("72", "72 - Sarthe"),
                            ("73", "73 - Savoie"),
                            ("74", "74 - Haute-Savoie"),
                            ("75", "75 - Paris"),
                            ("76", "76 - Seine-Maritime"),
                            ("77", "77 - Seine-et-Marne"),
                            ("78", "78 - Yvelines"),
                            ("79", "79 - Deux-Sèvres"),
                            ("80", "80 - Somme"),
                            ("81", "81 - Tarn"),
                            ("82", "82 - Tarn-et-Garonne"),
                            ("83", "83 - Var"),
                            ("84", "84 - Vaucluse"),
                            ("85", "85 - Vendée"),
                            ("86", "86 - Vienne"),
                            ("87", "87 - Haute-Vienne"),
                            ("88", "88 - Vosges"),
                            ("89", "89 - Yonne"),
                            ("90", "90 - Territoire de Belfort"),
                            ("91", "91 - Essonne"),
                            ("92", "92 - Hauts-de-Seine"),
                            ("93", "93 - Seine-Saint-Denis"),
                            ("94", "94 - Val-de-Marne"),
                            ("95", "95 - Val-d'Oise"),
                            ("971", "971 - Guadeloupe"),
                            ("972", "972 - Martinique"),
                            ("973", "973 - Guyane"),
                            ("974", "974 - La Réunion"),
                            ("975", "975 - Saint-Pierre-et-Miquelon"),
                            ("976", "976 - Mayotte"),
                            ("977", "977 - Saint-Barthélémy"),
                            ("978", "978 - Saint-Martin"),
                            ("984", "984 - Terres australes et antarctiques françaises"),
                            ("986", "986 - Wallis-et-Futuna"),
                            ("987", "987 - Polynésie française"),
                            ("988", "988 - Nouvelle-Calédonie"),
                            ("989", "989 - Île Clipperton"),
                        ],
                        db_index=True,
                        max_length=3,
                        verbose_name="département",
                    ),
                ),
                ("geocoding_score", models.FloatField(blank=True, null=True, verbose_name="score du geocoding")),
                (
                    "post_code",
                    models.CharField(
                        blank=True,
                        max_length=5,
                        validators=[itou.utils.validators.validate_post_code],
                        verbose_name="code postal",
                    ),
                ),
                (
                    "has_completed_welcoming_tour",
                    models.BooleanField(default=False, verbose_name="parcours de bienvenue effectué"),
                ),
                (
                    "title",
                    models.CharField(
                        blank=True,
                        choices=[("M", "Monsieur"), ("MME", "Madame")],
                        default="",
                        max_length=3,
                        verbose_name="civilité",
                    ),
                ),
                (
                    "external_data_source_history",
                    models.JSONField(
                        blank=True,
                        encoder=django.core.serializers.json.DjangoJSONEncoder,
                        null=True,
                        verbose_name="information sur la source des champs",
                    ),
                ),
                (
                    "identity_provider",
                    models.CharField(
                        choices=[
                            ("DJANGO", "Django"),
                            ("FC", "FranceConnect"),
                            ("IC", "Inclusion Connect"),
                            ("PC", "ProConnect"),
                            ("PEC", "Pôle emploi Connect"),
                        ],
                        default="DJANGO",
                        max_length=20,
                        verbose_name="fournisseur d'identité (SSO)",
                    ),
                ),
                (
                    "last_checked_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="date de dernière vérification"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("job_seeker", "candidat"),
                            ("prescriber", "prescripteur"),
                            ("employer", "employeur"),
                            ("labor_inspector", "inspecteur du travail"),
                            ("itou_staff", "administrateur"),
                        ],
                        max_length=20,
                        verbose_name="type",
                    ),
                ),
                (
                    "ban_api_resolved_address",
                    models.TextField(
                        blank=True, null=True, verbose_name="libellé d'adresse retourné par le dernier geocoding"
                    ),
                ),
                (
                    "geocoding_updated_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="dernière modification du geocoding"),
                ),
                (
                    "public_id",
                    models.UUIDField(default=uuid.uuid4, verbose_name="identifiant public opaque, pour les API"),
                ),
                (
                    "insee_city",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="cities.city"
                    ),
                ),
                (
                    "address_filled_at",
                    models.DateTimeField(
                        help_text="Mise à jour par autocomplétion de l'utilisateur",
                        null=True,
                        verbose_name="date de dernier remplissage de l'adresse",
                    ),
                ),
            ],
            options={
                "verbose_name": "user",
                "verbose_name_plural": "users",
                "abstract": False,
            },
            managers=[
                ("objects", itou.users.models.ItouUserManager()),
            ],
        ),
        migrations.CreateModel(
            name="JobSeekerProfile",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="jobseeker_profile",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="demandeur d'emploi",
                    ),
                ),
                (
                    "education_level",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("00", "Personne avec qualifications non-certifiantes"),
                            ("01", "Jamais scolarisé"),
                            ("10", "Troisième cycle ou école d'ingénieur"),
                            ("20", "Formation de niveau licence"),
                            ("30", "Formation de niveau BTS ou DUT"),
                            ("40", "Formation de niveau BAC"),
                            ("41", "Brevet de technicien ou baccalauréat professionnel"),
                            ("50", "Formation de niveau BEP ou CAP"),
                            ("51", "Diplôme obtenu CAP ou BEP"),
                            ("60", "Formation courte d'une durée d'un an"),
                            ("70", "Pas de formation au-delà de la scolarité obligatoire"),
                        ],
                        max_length=2,
                        verbose_name="niveau de formation (ASP)",
                    ),
                ),
                ("resourceless", models.BooleanField(default=False, verbose_name="sans ressource")),
                (
                    "rqth_employee",
                    models.BooleanField(
                        default=False,
                        help_text="Reconnaissance de la qualité de travailleur handicapé",
                        verbose_name="titulaire de la RQTH",
                    ),
                ),
                (
                    "oeth_employee",
                    models.BooleanField(
                        default=False,
                        help_text="L'obligation d’emploi des travailleurs handicapés",
                        verbose_name="bénéficiaire de la loi handicap (OETH)",
                    ),
                ),
                (
                    "pole_emploi_since",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Moins de 6 mois"),
                            ("02", "De 6 à 11 mois"),
                            ("03", "De 12 à 23 mois"),
                            ("04", "24 mois et plus"),
                        ],
                        max_length=2,
                        verbose_name="inscrit à France Travail depuis",
                    ),
                ),
                (
                    "unemployed_since",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Moins de 6 mois"),
                            ("02", "De 6 à 11 mois"),
                            ("03", "De 12 à 23 mois"),
                            ("04", "24 mois et plus"),
                        ],
                        max_length=2,
                        verbose_name="sans emploi depuis",
                    ),
                ),
                (
                    "rsa_allocation_since",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Moins de 6 mois"),
                            ("02", "De 6 à 11 mois"),
                            ("03", "De 12 à 23 mois"),
                            ("04", "24 mois et plus"),
                        ],
                        max_length=2,
                        verbose_name="allocataire du RSA depuis",
                    ),
                ),
                (
                    "ass_allocation_since",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Moins de 6 mois"),
                            ("02", "De 6 à 11 mois"),
                            ("03", "De 12 à 23 mois"),
                            ("04", "24 mois et plus"),
                        ],
                        max_length=2,
                        verbose_name="allocataire de l'ASS depuis",
                    ),
                ),
                (
                    "aah_allocation_since",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Moins de 6 mois"),
                            ("02", "De 6 à 11 mois"),
                            ("03", "De 12 à 23 mois"),
                            ("04", "24 mois et plus"),
                        ],
                        max_length=2,
                        verbose_name="allocataire de l'AAH depuis",
                    ),
                ),
                (
                    "ata_allocation_since",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Moins de 6 mois"),
                            ("02", "De 6 à 11 mois"),
                            ("03", "De 12 à 23 mois"),
                            ("04", "24 mois et plus"),
                        ],
                        max_length=2,
                        verbose_name="allocataire de l'ATA depuis",
                    ),
                ),
                (
                    "hexa_lane_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("AER", "Aérodrome"),
                            ("AGL", "Agglomération"),
                            ("AIRE", "Aire"),
                            ("ALL", "Allée"),
                            ("ACH", "Ancien chemin"),
                            ("ART", "Ancienne route"),
                            ("AV", "Avenue"),
                            ("BEGI", "Beguinage"),
                            ("BD", "Boulevard"),
                            ("BRG", "Bourg"),
                            ("CPG", "Camping"),
                            ("CAR", "Carrefour"),
                            ("CTRE", "Centre"),
                            ("CCAL", "Centre commercial"),
                            ("CHT", "Chateau"),
                            ("CHS", "Chaussee"),
                            ("CHEM", "Chemin"),
                            ("CHV", "Chemin vicinal"),
                            ("CITE", "Cité"),
                            ("CLOS", "Clos"),
                            ("CTR", "Contour"),
                            ("COR", "Corniche"),
                            ("COTE", "Coteaux"),
                            ("COUR", "Cour"),
                            ("CRS", "Cours"),
                            ("DSC", "Descente"),
                            ("DOM", "Domaine"),
                            ("ECL", "Ecluse"),
                            ("ESC", "Escalier"),
                            ("ESPA", "Espace"),
                            ("ESP", "Esplanade"),
                            ("FG", "Faubourg"),
                            ("FRM", "Ferme"),
                            ("FON", "Fontaine"),
                            ("GAL", "Galerie"),
                            ("GARE", "Gare"),
                            ("GBD", "Grand boulevard"),
                            ("GPL", "Grande place"),
                            ("GR", "Grande rue"),
                            ("GRI", "Grille"),
                            ("HAM", "Hameau"),
                            ("IMM", "Immeuble(s)"),
                            ("IMP", "Impasse"),
                            ("JARD", "Jardin"),
                            ("LD", "Lieu-dit"),
                            ("LOT", "Lotissement"),
                            ("MAIL", "Mail"),
                            ("MAIS", "Maison"),
                            ("MAS", "Mas"),
                            ("MTE", "Montee"),
                            ("PARC", "Parc"),
                            ("PRV", "Parvis"),
                            ("PAS", "Passage"),
                            ("PLE", "Passerelle"),
                            ("PCH", "Petit chemin"),
                            ("PRT", "Petite route"),
                            ("PTR", "Petite rue"),
                            ("PL", "Place"),
                            ("PTTE", "Placette"),
                            ("PLN", "Plaine"),
                            ("PLAN", "Plan"),
                            ("PLT", "Plateau"),
                            ("PONT", "Pont"),
                            ("PORT", "Port"),
                            ("PROM", "Promenade"),
                            ("QUAI", "Quai"),
                            ("QUAR", "Quartier"),
                            ("RPE", "Rampe"),
                            ("REMP", "Rempart"),
                            ("RES", "Residence"),
                            ("ROC", "Rocade"),
                            ("RPT", "Rond-point"),
                            ("RTD", "Rotonde"),
                            ("RTE", "Route"),
                            ("RUE", "Rue"),
                            ("RLE", "Ruelle"),
                            ("SEN", "Sente"),
                            ("SENT", "Sentier"),
                            ("SQ", "Square"),
                            ("TPL", "Terre plein"),
                            ("TRAV", "Traverse"),
                            ("VEN", "Venelle"),
                            ("VTE", "Vieille route"),
                            ("VCHE", "Vieux chemin"),
                            ("VILL", "Villa"),
                            ("VLGE", "Village"),
                            ("VOIE", "Voie"),
                            ("ZONE", "Zone"),
                            ("ZA", "Zone d'activite"),
                            ("ZAC", "Zone d'amenagement concerte"),
                            ("ZAD", "Zone d'amenagement differe"),
                            ("ZI", "Zone industrielle"),
                            ("ZUP", "Zone urbanisation prio"),
                        ],
                        max_length=4,
                        verbose_name="type de voie",
                    ),
                ),
                (
                    "hexa_std_extension",
                    models.CharField(
                        blank=True,
                        choices=[("B", "Bis"), ("T", "Ter"), ("Q", "Quater"), ("C", "Quinquies")],
                        default="",
                        max_length=1,
                        verbose_name="extension de voie",
                    ),
                ),
                (
                    "hexa_lane_number",
                    models.CharField(blank=True, default="", max_length=10, verbose_name="numéro de la voie"),
                ),
                ("hexa_lane_name", models.CharField(blank=True, max_length=120, verbose_name="nom de la voie")),
                ("hexa_post_code", models.CharField(blank=True, max_length=6, verbose_name="code postal")),
                (
                    "hexa_commune",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        to="asp.commune",
                        verbose_name="commune (ref. ASP)",
                    ),
                ),
                (
                    "hexa_non_std_extension",
                    models.CharField(
                        blank=True, default="", max_length=10, verbose_name="extension de voie (non-repertoriée)"
                    ),
                ),
                (
                    "has_rsa_allocation",
                    models.CharField(
                        choices=[
                            ("NON", "Non bénéficiaire du RSA"),
                            ("OUI-M", "Bénéficiaire du RSA et majoré"),
                            ("OUI-NM", "Bénéficiaire du RSA et non-majoré"),
                        ],
                        default="NON",
                        max_length=6,
                        verbose_name="salarié bénéficiaire du RSA",
                    ),
                ),
                (
                    "previous_employer_kind",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Entreprise d'insertion"),
                            ("02", "Entreprise de travail temporaire d'insertion"),
                            ("03", "Association intermédiaire"),
                            ("04", "Atelier chantier d'insertion"),
                            ("05", "Etablissement et service d'aide par le travail"),
                            ("06", "Entreprise adaptée"),
                            ("07", "Autre"),
                        ],
                        max_length=2,
                        verbose_name="précédent employeur",
                    ),
                ),
                (
                    "hexa_additional_address",
                    models.CharField(blank=True, max_length=32, verbose_name="complément d'adresse"),
                ),
                (
                    "pe_obfuscated_nir",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Identifiant France Travail chiffré, utilisé dans la communication à France Travail. "
                            "Son existence implique que le nom, prénom, date de naissance et NIR de ce candidat sont "
                            "connus et valides du point de vue de France Travail.",
                        ),
                        max_length=48,
                        null=True,
                        verbose_name="identifiant France Travail chiffré",
                    ),
                ),
                (
                    "pe_last_certification_attempt_at",
                    models.DateTimeField(
                        help_text="Date à laquelle nous avons tenté pour la dernière fois de certifier ce candidat",
                        null=True,
                        verbose_name="date de la dernière tentative de certification",
                    ),
                ),
                (
                    "birth_country",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="jobseeker_profiles_born_here",
                        to="asp.country",
                        verbose_name="pays de naissance",
                    ),
                ),
                (
                    "birth_place",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="jobseeker_profiles_born_here",
                        to="asp.commune",
                        verbose_name="commune de naissance",
                    ),
                ),
                (
                    "lack_of_pole_emploi_id_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("FORGOTTEN", "Identifiant France Travail oublié"),
                            ("NOT_REGISTERED", "Non inscrit auprès de France Travail"),
                        ],
                        help_text="Indiquez la raison de l'absence d'identifiant France Travail.<br>Renseigner "
                        "l'identifiant France Travail des candidats inscrits permet d'instruire instantanément "
                        "votre demande.<br>Dans le cas contraire un délai de deux jours est nécessaire pour "
                        "effectuer manuellement les vérifications d’usage.",
                        verbose_name="pas d'identifiant France Travail\xa0?",
                    ),
                ),
                (
                    "pole_emploi_id",
                    models.CharField(
                        blank=True,
                        help_text="7 chiffres suivis d'une 1 lettre ou d'un chiffre.",
                        max_length=8,
                        validators=[
                            itou.utils.validators.validate_pole_emploi_id,
                            django.core.validators.MinLengthValidator(8),
                        ],
                        verbose_name="identifiant France Travail",
                    ),
                ),
                (
                    "lack_of_nir_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("TEMPORARY_NUMBER", "Numéro temporaire (NIA/NTT)"),
                            ("NO_NIR", "Pas de numéro de sécurité sociale"),
                            (
                                "NIR_ASSOCIATED_TO_OTHER",
                                "Le numéro de sécurité sociale est associé à quelqu'un d'autre",
                            ),
                        ],
                        help_text="Indiquez la raison de l'absence de NIR.",
                        max_length=30,
                        verbose_name="pas de NIR ?",
                    ),
                ),
                (
                    "nir",
                    models.CharField(
                        blank=True, max_length=15, validators=[itou.utils.validators.validate_nir], verbose_name="NIR"
                    ),
                ),
                (
                    "asp_uid",
                    models.TextField(
                        blank=True,
                        help_text="Si vide, une valeur sera assignée automatiquement.",
                        max_length=30,
                        unique=True,
                        verbose_name="ID unique envoyé à l'ASP",
                    ),
                ),
            ],
            options={
                "verbose_name": "profil demandeur d'emploi",
                "verbose_name_plural": "profils demandeur d'emploi",
            },
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Upper("email"), name="text_pattern_ops"
                ),
                name="users_user_email_upper",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        models.Q(("kind", "itou_staff"), _negated=True), ("is_staff", False), ("is_superuser", False)
                    ),
                    models.Q(("is_staff", True), ("kind", "itou_staff")),
                    _connector="OR",
                ),
                name="staff_and_superusers",
                violation_error_message="Seul un utilisateur ITOU_STAFF peut avoir is_staff ou is_superuser de vrai.",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("kind", "itou_staff"),
                    ("kind", "job_seeker"),
                    ("kind", "prescriber"),
                    ("kind", "employer"),
                    ("kind", "labor_inspector"),
                    _connector="OR",
                ),
                name="has_kind",
                violation_error_message="Le type d’utilisateur est incorrect.",
            ),
        ),
        migrations.AddConstraint(
            model_name="jobseekerprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(("lack_of_nir_reason", ""), ("nir", ""), _connector="OR"),
                name="jobseekerprofile_lack_of_nir_reason_or_nir",
                violation_error_message="Un utilisateur ayant un NIR ne peut avoir un motif justifiant l'absence de "
                "son NIR.",
            ),
        ),
        migrations.AddConstraint(
            model_name="jobseekerprofile",
            constraint=models.UniqueConstraint(
                models.F("nir"),
                condition=models.Q(("nir", ""), _negated=True),
                name="jobseekerprofile_unique_nir_if_not_empty",
                violation_error_code="unique_nir_if_not_empty",
                violation_error_message="Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.",
            ),
        ),
    ]
