# CodeRabbit

[CodeRabbit](https://www.coderabbit.ai/) est un outil de revue de code basé sur un LLM. Il publie des commentaires sur les PR, mais ne génère pas de commit.

## Commandes utiles

CodeRabbit n’analyse que les PR qui portent l’étiquette `review-coderabbit`. Une fois l’étiquette posée, chaque nouveau commit déclenche une nouvelle analyse.

Les commandes se tapent dans un nouveau commentaire de la PR :

| Commande | Effet |
|---|---|
| `@coderabbitai review` | Analyse les changements depuis la dernière revue (fonctionne aussi sans l’étiquette) |
| `@coderabbitai full review` | Analyse toute la PR depuis zéro |
| `@coderabbitai pause` / `@coderabbitai resume` | Suspend ou reprend les revues automatiques |
| `@coderabbitai resolve` | Marque tous les commentaires de CodeRabbit comme résolus (pas autorisé pour l’auteur de la PR) |
| `@coderabbitai generate sequence diagram` | Génère un diagramme de séquence des changements, pratique pour comprendre une grosse PR |
| `@coderabbitai help` | Liste les commandes |

Pour qu’une PR ne soit jamais analysée automatiquement, écrivez `@coderabbitai ignore` dans sa description (l’écrire dans un commentaire ne suffit pas).

## Poser des questions

Il est possible d’interroger CodeRabbit sur la PR : répondez à l’un de ses commentaires, ou écrivez un nouveau commentaire, en mentionnant `@coderabbitai`.

- *@coderabbitai pourquoi est-ce un problème ? Propose une alternative.*
- *@coderabbitai cette vue fait-elle des requêtes N+1 ?*
- *@coderabbitai quels cas de test manquent pour ce changement ?*

Plus la question est précise, meilleure est la réponse. Les réponses peuvent être fausses : signalez l’erreur en expliquant pourquoi.

## Enregistrer nos conventions

Si une remarque ne correspond pas à nos pratiques, indiquez-le en mentionnant `@coderabbitai` et en donnant la raison :

> @coderabbitai les textes visibles par les utilisateurs sont en français : ne pas suggérer de les traduire.

CodeRabbit enregistre alors un *learning* (section "*Learnings added*" de la réponse), pris en compte dans les revues suivantes une fois la PR fusionnée. Pour une exception ponctuelle, pas besoin de *learning* : résolvez simplement le commentaire. Les *learnings* sont listés sur [app.coderabbit.ai/learnings](https://app.coderabbit.ai/learnings).

## Corriger avec un autre LLM

Chaque commentaire contient un bloc dépliable "*Prompt for AI Agents*". Copiez-le dans votre assistant de code (Claude Code, Copilot…) pour appliquer la correction en local.

## Pour aller plus loin

- [Gérer les revues avec les commandes](https://docs.coderabbit.ai/guides/commands)
- [Référence complète des commandes](https://docs.coderabbit.ai/reference/review-commands)
- [Poser des questions dans les PR](https://docs.coderabbit.ai/guide/chat)
- [*Learnings*](https://docs.coderabbit.ai/knowledge-base/learnings)
