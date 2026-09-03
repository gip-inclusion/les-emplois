# Audit Trail

## Contexte

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
- Est-ce que le navigateur utilisé pour faire la demande est le
  navigateur habituel de cet utilisateur ?
- Est-ce que la réputation de l’IP utilisée pour faire la demande est
  bonne ?
- Est-ce que le mot de passe a été réinitialisé récemment ?
- Est-ce que l’utilisateur est déjà connecté ?

Cette vérification implique de stocker la configuration (adresse IP,
navigateur utilisé) habituelle de chaque utilisateur.


## Implémentation

La proposition est d’implémenter un [audit
trail](https://en.wikipedia.org/wiki/Audit_trail) sous forme d’une
table dans postgresql.

Liste des évènements stockés dans l’audit trail :

- La connexion d’un utilisateur

Liste des évènements qui pourraient être stockés à l’avenir dans l’audit trail :

- export de donnée,
- réinitialisation de 2FA,
- ajout d’un administrateur à une organisation,
- échec de connexion.

L’implémentation proposée stocke les évènements dans une table
contenant :

- date,
- type de l’évènement,
- identifiant de l’utilisateur,
- adresse IP,
- cookie de corrélation,
- data (JSONField).

Le champ `data` sert à stocker des informations en lien avec
l’évènement. Par exemple pour l’évènement « granted an admin » on sait
qui l’a fait, grâce à la colonne identifiant de l’utilisateur, mais
pas qui a été nommé admin ni dans quelle organisation. Dans ce cas on
peut ajouter `{"new_admin": user_id, "in_org": org_id}` au champ data.

Une énumération pour lister les types d’évènements reconnus.

Et un manager sur le modèle pour insérer un évènement :

    AuditTrail.objects.log(AuditTrailEventType.CONNECTION, request)


### Cookie de corrélation

Un middleware place et renouvelle à chaque requête un « cookie de
corrélation » `HttpOnly` d’une durée de vie de 45 jours contenant un
jeton aléatoire.

Si une machine n’est pas utilisée pendant longtemps, son cookie de
corrélation est alors perdu, on considérera qu’on ne connaît pas cette
machine.

Si une machine est utilisée régulièrement, son cookie de corrélation
peut survivre indéfiniment.

Ce cookie nous permet de suivre un navigateur dans l’audit trail.

Un cookie de corrélation qui n’existe pas dans l’audit trail indique
que c’est un navigateur utilisé pour la première fois.


## Projets potentiels basés sur l’audit trail

- [Notification en temps réel à l’utilisateur légitime lors d’un export ou d’une connexion depuis un appareil ou une adresse IP inhabituelle](https://app.notion.com/p/gip-inclusion/Notification-en-temps-r-el-l-utilisateur-l-gitime-lors-d-un-export-ou-d-une-connexion-depuis-un-ap-34c5f321b60480aa84a0fa256987fbe3)
- Couper les accès d’acteurs malveillants.
- Bloquer ou alerter à la connexion si elle est suspecte (déclencher
  un 2FA par email ?).
- Email d’information de connexion suspecte (ou d’action suspecte).
- Rate-limiting d’opérations sensibles (export de données personnelles).
- Exposer des informations de l’audit trail sous forme de metrics Prometheus.
- Noter la crédibilité d’une action en fonction de l’heure (23h, ou
  samedi 14h, c’est suspect).
- La fonction qui ajoute à l’audit trail pourrait aussi s’occuper du
  rate-limiting et des vérifications de crédibilité, et effectuer le
  blocage.


### Projets et pistes autour des adresses IP

Une adresse IP permet d’obtenir des informations pertinentes :

- geolocalisation approximative,
- [AS](https://fr.wikipedia.org/wiki/Autonomous_System),
- comportement relevé par des honeypots, par exemple via https://app.crowdsec.net/cti,
- présence sur des listes d’IP « suspectes » (points de sortie TOR, VPNs).
- Mesure de la crédibilité des adresses IP
- Géolocalisation d’adresses IP

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


## Annexes

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


### Données personnelles

On peut collecter les données nécessaires pour la sécurité de la
plateforme sur le fondement de l’intérêt légitime.


### Durée de conservation ?

Un an pour rester sous la limite des trois ans (prévus par le décret),
et pour rester sous les 13 mois max pour les comptes sans activité.


## Tâches à effectuer

### Modification de la politique de confidentialité du GIP (sur le site vitrine)

### Indiquer ce traitement au registre des activités de traitement

Décrire le fonctionnement du cookie de corrélation et à quoi il sert.


### Ajouter le cookie de corrélation au bandeau de cookies

En « cookie nécessaire ».


## Alternatives

### Datadog

Il serait presque possible d’utiliser Datadog, que nous utilisons
déjà, avec des webhook pour être notifiés d’évènements (rate-limit
atteint, …).

Mais Datadog ne serait pas requêtable pour obtenir une information
comme : « est-ce que telle demande de 2FA est valide » ou plus
largement « Est-ce que telle connexion est suspecte ? », on ne
pourrait donc pas bloquer à priori, uniquement à posteriori.

Aussi France Travail n’utilise pas Datadog mais Dynatrace, ce qui
complexifie la migration.

Aussi être aussi dépendant d’un système externe est une source de
risques qu’on préfère éviter.

Finalement maintenir un audit trail chez nous est plus léger à
maintenir.

### Append-only

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

Nous utilisons donc une table normale, avec des droits normaux,
et managée par Django.
