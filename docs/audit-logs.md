# Audit Logs

## Pourquoi ?

cf. [carte notion](https://app.notion.com/p/gip-inclusion/ADMIN-DJANGO-Nouvelle-fonctionnalit-pour-envoyer-un-lien-de-r-initialisation-des-param-tres-2FA-3b95f321b604803b96dcfe571d46330b)

La réinitialisation de la configuration 2FA d’un utilisateur est une
action sensible qui sera mise à l’épreuve par des acteurs
malveillants.

La réinitialisation doit passer par une validation humaine, soit d’un
administrateur de l’organisation, soit par le support.

Nous souhaitons aider l’administrateur et le support en leur affichant
une mesure de la crédibilité des demandes de réinitialisation de 2FA
en se basant sur plusieurs critères :

- Est-ce que l’IP utilisée pour faire la demande est une IP habituelle
  pour cet utilisateur ?
- Est-ce que la réputation de l’IP utilisée pour faire la demande est
  bonne ?
- Est-ce que le mot de passe a été réinitialisé récemment ?
- Est-ce que l’utilisateur est déjà connecté ?

Cette vérification implique de stocker la configuration (adresse IP,
navigateur utilisé) habituelle de chaque utilisateur.


## Proposition

La proposition est d’implémenter un [audit
trail](https://en.wikipedia.org/wiki/Audit_trail).

Les seuls évènements à enregistrer pour le besoin de la
réinitialisation de 2FA sont la connexion et la réinitialisation de
mot de passe, mais cette proposition permet aussi d’y stocker tout
évènement important comme :

- export de donnée,
- ajout d’un administrateur à une organisation,
- échec de connexion.

qui pourrait permettre à l’avenir de détecter automatiquement des
comportements suspects.


### Implémentation

L’implémentation proposée stocke les évènements dans une table
contenant :

- date,
- type de l’évènement,
- identifiant de l’utilisateur,
- identifiant de la session de l’utilisateur,
- adresse IP,
- entêtes de la requête HTTP, sans les cookies (JSONField),
- cookies (JSONField),
- data (JSONField).

Le champ `data` sert à stocker des informations en lien avec
l’évènement. Par exemple pour l’évènement « granted an admin » on sait
qui l’a fait, grâce à la colonne identifiant de l’utilisateur, mais
pas qui a été nommé admin ni dans quelle organisation. Dans ce cas on
peut ajouter `{"new_admin": user_id, "in_org": org_id}` au champ data.

Une énumération pour lister les types d’évènements reconnus.

Et un manager sur le modèle pour ajouter un évènement :

    AuditLog.objects.log(AuditLogEventType.PASSWORD_RESET, request, data={"meta": "data", "goes": "here"})


## Discussions

### Justification dans le cadre de la réinitialisation de 2FA

La procédure de réinitialisation de 2FA sera mise à l’épreuve par des
acteurs malveillants.

Le 2FA **est** la technologie protegeant un compte. Protéger la
réinitialisation de 2FA ne peut donc pas se reposer sur une solution
technologique : si une solution technologique permettait de prouver
l’identité d’un utilisateur, cette technologie serait utilisée à la
place du 2FA, ou serait un autre 2FA.

Une de ces solutions technologiques est d’ailleurs déjà en place sous
forme de second 2FA : le code de secours, qui permet à l’utilisateur
de se connecter et de réinitialiser son TOTP en autonomie.

Accepter d’autres solutions de 2FA comme WebAuthn permettrait aussi
aux utilisateurs d’avoir une alternative en cas de perte de l’un de
leur second facteur. Mais le budget est conséquent ([une clé webauthn
coûte environ
70 €](https://www.yubico.com/fr/product/yubikey-5-series/yubikey-5c-nfc/),
à multiplier par le nombre d’utilisateurs).

Il reste la solution non technologique : dans l’idéal aller voir son
administrateur et lui demander de vive voix la réinitialisation.

Les contraintes de la réalité (par exemple : l’administrateur **est**
l’utilisateur qui a perdu son 2FA, le télétravail, un déplacement
professionnel…) font que la solution idéale n’est pas toujours
possible.

Certaines réinitialisations se feront donc à distance, et seront
risquées :

- L’administrateur est au téléphone avec un acteur malveillant qui
  usurpe le numéro de téléphone et la voix de sa victime.
- L’administrateur est en visio avec un acteur malveillant qui usurpe
  l’image et la voix de sa victime.
- L’administrateur est prêt à effectuer une réinitialisation de 2FA
  par simple demande par email.

Aussi il est possible d’automatiquement détecter que certaines
demandes de réinitialisation sont faites par des acteurs
malveillants : demande faite deux minutes après une réinitialisation
de mot de passe, provenant d’une IP d’une puissance étrangère réputée
pour mener ce genre d’attaques.

Laisser aux administrateurs ou au support toute la charge de prendre
la décision de réinitialiser un 2FA alors que techniquement il est
possible de détecter certaines demandes illégitimes n’est pas idéal.

C’est pourquoi certains paramètres, à la connexion et au changement de
mot de passe, doivent être conservés afin de remonter une information
aux administrateurs en charge de prendre la décision de réinitialiser
un 2FA : est-ce que la demande provient de la machine habituelle de
l’utilisateur ou semble-elle provenir d’un acteur malveillant.

Conserver l’IP, et d’autres paramètres de connexion, n’implique pas de
les divulguer à un administrateur : l’administrateur voit uniquement
si c’est la machine habituelle de l’utilisateur qui est utilisée pour
faire la demande de réinitialisation.


### Délai minimum

Il est possible d’imposer un délai minimum entre une réinitialisation
de mot de passe et une réinitialisation de 2FA, afin de bloquer un
attaquant qui vient de prendre le contrôle de la boite mail de sa
cible, qui vient de réinitialiser le mot de passe par mail, et qui
tente de réinitialiser le 2FA.

Il est aussi possible d’imposer un délai entre la dernière connexion
réussie et la réinitialisation de 2FA, pour s’assurer qu’il est vrai
que le second facteur est perdu. Mais ce n’est peut-être pas
raisonnable de bloquer des actes métiers légitimes, ou obligatoires.

Proposition : à discuter.


### Quelles données utiliser

En utilisant suffisamment de points de donnée il est possible
d’identifier un navigateur (et donc son utilisateur) de manière
presque unique (cf. [amiunique.org](https://amiunique.org/fr),
[Browser Fingerprinting](https://en.wikipedia.org/wiki/Device_fingerprint#Browser_fingerprinting)).

Certaines données sont déjà disponibles côté serveur, d’autres
nécessitent l’exécution de JavaScript côté client pour les récolter.

Il est possible d’exécuter du JavaScript à la connexion et à la
demande de réinitialisation de 2FA pour les stocker et les corréler.

Mais la complexité des mesures client-side, leur aspect intrusif, et
le potentiellement faible bénéfice qu’elles apportent par rapport aux
données déjà disponibles n’encourage pas cette pratique.

Les données disponibles côté serveur sont :

- Adresse IP
- En-tête `User-Agent`
- En-tête `Accept`
- En-tête `Accept-Language`
- En-tête `Accept-Encoding`
- En-tête `Do Not Track`
- En-tête `Upgrade Insecure Requests`
- Cookies

Dans mon cas, selon amiunique.org :

- Mon `User-Agent` n’est utilisé que par 0.64 % de la population.
- Mon en-tête `Accept` est utilisée par 22.25 % de la population.
- Mon en-tête `Accept-Encoding` est utilisée par 42.85 % de la population.
- Mon en-tête `Accept-Language` est utilisée par 0.02 % de la population.
- Mon en-tête `Upgrade-Insecure-Requests` est utilisée par 89.09 % de la population.
- Mon en-tête "Do Not Track" est utilisée par 25.80 % de la population.

Ces données permettent de m’identifier de manière assez précise, sans
prendre en compte de mesures côté navigateur.

Dans la population de nos utilisateurs les valeurs sont probablement
moins extrêmes, mais le but n’est pas de distinguer deux utilisateurs
légitimes, mais un utilisateur légitime d’un acteur malveillant.

Proposition : utiliser uniquement des données déjà visibles côté
serveur et se passer de la complexité d’exécuter du JavaScript pour en
récolter d’autres.


### Alerte automatique lors d’une connexion suspecte

L’envoi automatique d’un email à un utilisateur lorsqu’une connexion à
son compte est suspecte devient possible grâce à l’audit log.

Proposition : c’est un autre projet, à garder en tête.


### Utilisation d’un cookie spécifique

Un cookie `HttpOnly` contenant un jeton aléatoire pourrait être déposé
sur les navigateurs des utilisateurs avec une durée de vie élevée. Ce
cookie pourrait être utilisé comme moyen fiable de reconnaître le
navigateur d’une session à l’autre.

Dans le cadre de la réinitialisation de 2FA : une demande faite avec
un navigateur qui contient le cookie de la bonne personne peut être
considérée comme très crédible.

Cette donnée seule surpasse probablement tous les autres point de
données cumulés en terme de qualité pour montrer, lors d’une demande
de réinitialisation de 2FA, si la demande est faite par la machine de
l’utilisateur ou non.

Dans le strict contexte de la réinitialisation de 2FA, se fier à ce
cookie pourrait nous dispenser de stocker d’autres informations
personnelles.

Cependant dans le contexte plus large d’audit trail les autres données
sont peut-être tout de même pertinentes ?

Proposition : en discuter.

Question : est-ce qu’un tel cookie nécessite le consentement préalable
de l’utilisateur ?


### Le cas des ordinateurs publics

Le système est fragile aux ordinateurs publics : un utilisateur qui se
connecte sur une machine publique marque cette machine comme « de
confiance » pour notre système. Il devient légitime de faire une
demande de réinitialisation de 2FA depuis cette machine.

Moyens de protection :

- La demande de réinitialisation de 2FA ne doit être possible
  qu’immédiatement après avoir saisi son mot de passe, pas n’importe
  quand, pour s’assurer que l’individu qui fait la demande connaît le
  mot de passe.
- Une demande de réinitialisation de 2FA faite immédiatement après une
  ré-initialisation de mot de passe doit être marquée comme hautement
  suspecte, ou bloquée (voir la discussion « Délai minimum ».


### Pertinence des données

Pour le moment nous ne stockons pas ces données, il nous est
impossible de mesurer combien de faux positifs nous aurions (un
utilisateur légitime qui se connecte avec une configuration considérée
suspecte) ni combien de faux négatifs nous aurions (un acteur
malveillant qui se connecte avec une configuration suffisamment
semblable à sa cible pour ne pas lever d’alerte).

Uniquement après avoir mis en place cette solution nous pourrons
mesurer le taux de faux positifs (à la connexion d’un utilisateur si
on arrive pas a le corréler avec ses sessions précédentes).

Cependant, même après avoir mis en place la solution il sera difficile
(impossible ?) de mesurer le taux de faux négatifs : il nous faudrait
un acteur malveillant, et voir s’il a une bonne corrélation avec des
comptes existants.

Proposition : mesurer le taux de faux positifs une fois suffisamment de
donnée récoltée.

Point d’attention : si la solution du « cookie spécifique » est
adoptée, ce chapitre n’a plus lieu d’exister.


### Crédibilité des adresses IP

Une adresse IP permet d’obtenir des informations pertinentes :

- geolocalisation approximative,
- [AS](https://fr.wikipedia.org/wiki/Autonomous_System),
- comportement relevé par des honeypots, par exemple via https://app.crowdsec.net/cti,
- présence sur des listes d’IP « suspectes » (points de sortie TOR, VPNs).

La géolocalisation peut donner un indice : les requêtes provenant de
départements français sont plus crédibles.

L’AS peut nous indiquer si c’est un réseau dédié aux humains ou aux
serveurs, une requête provenant d’un FAI français est plus crédible.

L’AS peut aussi nous permettre de corréler deux IP différentes mais
appartenant probablement au même utilisateur : si l’utilisateur
utilise toujours des IP différentes du même FAI, et qu’il fait une
demande de réinitialisation avec une IP différente mais du même FAI,
la demande reste crédible.

Les informations données par crowdsec ne sont pas particulièrement
pertinentes dans notre cas, crowdsec piège, en utilisant des
honeypots, des serveurs malveillants, pas des utilisateurs
malveillants.

Les IP « suspectes » (points de sortie TOR et VPN) peuvent aussi être
un indice : si un utilisateur est connu pour ne jamais utiliser TOR et
qu’une demande de réinitialisation de 2FA pour son compte provient de
ToR, la demande perd beaucoup en crédibilité.

Proposition : repousser l’étude de l’adresse IP à une version
ultérieure.

Point d’attention : si la solution du « cookie spécifique » est
adoptée, ce chapitre n’a peut-être plus lieu d’exister.


### Champ « identifiant de la session de l’utilisateur »

Pour la carte [Rendre impossible l’existence de deux sessions
simultanées](https://app.notion.com/p/gip-inclusion/Rendre-impossible-l-existence-de-deux-sessions-simultan-es-34c5f321b6048076b59ce3175853c496?v=2845f321b60480bd9ef6000c92a2d6ab&source=copy_link) on a plusieurs possibilités :

- Utiliser la table des évènements pour y chercher les autres sessions
  d’un utilisateur et les fermer.
- Utiliser une table pour joindre les sessions et les utilisateurs.
- Modifier le modèle des sessions pour y ajouter une colonne user_id.


Si le choix est fait d’utiliser la table d’évènements il est
nécessaire de stocker l’identifiant de la session dans la table des
évènements.

Cependant si la carte « rendre impossible l’existence de deux sessions
simultanées » est implémentée sans utiliser la table des évènements il
n’est plus nécessaire de stocker l’identifiant de session dans la
table des évènements : un utilisateur ne pourra avoir qu’une session,
l’identifiant de session ne nous donnera aucune information
supplémentaire.

Proposition : débattons-en.


### À propos d’append-only

Il semble intéressant de garantir qu’un attaquant ne puisse pas
modifier ou supprimer des enregistrements de cette table.

Cependant il est difficile de rendre une table `insert-only` ou
`append-only` : il faudrait pour cela que Django se connecte à
postgres avec un rôle qui ne serait pas propriétaire de la table :

> There is no need to grant privileges to the owner of an object
> (usually the user that created it), as the owner has all privileges by
> default. (The owner could, however, choose to revoke some of their own
> privileges for safety.)
_ https://www.postgresql.org/docs/current/sql-grant.html

Il faudrait configurer ce rôle pour qu’il ai tous les droits **sauf**
`UPDATE` et `DELETE` sur la table des évènements.

Aussi si un attaquant peut exécuter des `INSERT` ou des `DELETE`,
est-ce que c’est toujours le rôle de la table des évènements de nous
éclairer sur l’attaque ?

Proposition : utiliser une table normale, avec des droits normaux,
managée par Django.


### Données personnelles

On peut collecter les données nécessaires pour la sécurité du 2FA sur
le fondement de l’intérêt légitime.

Mais cette proposition étend largement de « sécurité du 2FA » à « un
journal des évènements », on doit pouvoir justifier pourquoi on a ces
données et en quoi elles sont **nécessaires**.


### Durée de conservation ?

Un an pour rester sous la limite des trois ans (prévus par le décret), et pour rester sous les 13 mois max pour les comptes sans activité.


### Modification de la politique de confidentialité du GIP (sur le site vitrine)

### Indiquer ce traitement au registre des activités de traitement

### Prometheus metrics

Si l’audit log enregistre une variété d’évènements il deviendra
intéressant d’en faire des graphiques et des alertes automatiques :

- Si le nombre de tentative de password reset est plus haute que d’habitude.
- Si le nombre de téléchargements d’export de données est plus élevé que d’habitude.
- …
