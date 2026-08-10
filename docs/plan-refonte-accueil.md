# Plan — Refonte de la page d'accueil (« Aujourd'hui »)

Objectif : la page d'accueil (`frontend/src/TodayPage.tsx`) est perçue comme **surchargée et non fonctionnelle**. Ce plan la restructure en une page calme, cohérente et utile, sans nouvelle dépendance. Travailler étape par étape, dans l'ordre ; chaque étape doit laisser `npm run build` vert.

## Constat (audit du 2026-08-10)

Problèmes observés sur https://jarvis.famillelallier.net/ et dans le code :

1. **Titre en double** — le `<h1>Aujourd'hui</h1>` de `TodayPage.tsx` est immédiatement suivi du `<h2>Aujourd'hui</h2>` de `DailyBriefing.tsx`.
2. **Information en double** — `DailyBriefing` affiche déjà les RDV du jour, les tâches dues et les tâches en retard (via `GET /briefing`), puis `TodayPage` ré-affiche une section « Tâches du jour » construite à partir d'un second fetch (`useTasks`). Deux sources pour la même donnée, qui peuvent se contredire.
3. **Rangée du haut incohérente** (`.today-top`) — trois widgets sans rapport entre eux sont alignés en flex : un chronomètre (`SessionTimer`, gros affichage 32px), un compteur de tâches (`TaskCountWidget`, encore un fetch séparé de `/tasks/count`), et la carte santé (`HealthStatus` : « État : ok / Base de données : up / Dernière vérification… »). Les baselines sont désalignées (chaque widget a ses propres `margin-bottom`), et la carte santé est un détail d'opérations, pas une info de page d'accueil.
4. **Alignement de texte cassé** — `.app` dans `App.css` impose `text-align: center` globalement ; `.briefing` et quelques classes le remettent à `left`, mais les titres de section de TodayPage (« Tâches du jour », « Habitudes du jour »…) restent centrés. Résultat : un mélange centré/aligné-gauche qui donne l'impression d'une page cassée.
5. **Empilement de sections vides** — quand il n'y a rien à afficher, la page devient une pile de « Aucune tâche due aujourd'hui. », « Aucune habitude pour l'instant. », etc. Beaucoup de bruit, zéro valeur.
6. **Capture rapide bloquante** — `handleCaptureSubmit` crée une session de chat puis **draine tout le stream LLM** avant d'afficher « Envoyé ✓ ». L'utilisateur regarde « Envoi… » pendant toute la génération du modèle : c'est ça, le ressenti « non fonctionnel ». De plus, rien ne se rafraîchit ensuite — si le secrétaire a créé une tâche/RDV, la page ne le montre pas.
7. **Styles incohérents** — `TodayPage` embarque son propre bloc `STYLES` avec une palette différente (indigo `#4f46e5`, verts/rouges pleins, fallback `var(--border-color, #ccc)` alors que la variable définie dans `index.css` s'appelle `--border`). `App.css` référence aussi `var(--accent)` qui n'est **définie nulle part** (outlines de focus invisibles). En mode sombre, les fallbacks `#ccc`/`#ddd` détonnent.
8. **Français approximatif** — « 1 tâches », « 1 actives » (pluriel non accordé) ; les dates passent par `toLocaleString(undefined, …)` donc s'affichent selon la locale du navigateur (« 4:11:22 AM » sur la carte santé).

## Étape 1 — Restructurer l'information (fichier principal : `TodayPage.tsx`)

1. **Un seul en-tête.** Garder le `<h1>` de la page, y ajouter la date du jour formatée en français (`toLocaleDateString('fr-CA', { weekday: 'long', day: 'numeric', month: 'long' })`). Supprimer le `<h2 className="briefing-title">` dans `DailyBriefing.tsx` (le composant n'est utilisé que sur l'accueil).
2. **Une seule source pour les tâches du jour.** Supprimer la section « Tâches du jour » de `TodayPage` et son filtrage `isDueTodayOrOverdue`/`useTasks` ; `DailyBriefing` devient la seule vitrine des RDV + tâches dues + tâches en retard. (Si on veut cocher une tâche depuis l'accueil, ajouter l'action dans `DailyBriefing` via un `PUT /tasks/{id}` — optionnel, pas bloquant.)
3. **Supprimer `TaskCountWidget` de l'accueil.** C'est un troisième fetch pour une info déjà couverte par le briefing. Le composant peut rester dans le repo (utilisé nulle part ailleurs → le supprimer complètement avec sa CSS `.task-count*`).
4. **Reléguer `HealthStatus`.** Le retirer de `.today-top`. Le remplacer par une pastille discrète (point vert/rouge + tooltip) placée en bout de nav dans `App.tsx`, ou en pied de page. Garder `useHealthPoll` tel quel ; seule la présentation change. La carte détaillée peut vivre ailleurs (ou n'apparaître qu'en cas d'erreur : afficher un bandeau seulement si `status !== ok`).
5. **SessionTimer : compact ou ailleurs.** S'il reste sur l'accueil, le réduire à une ligne (heure écoulée + un bouton) alignée à droite de l'en-tête, sans le display 32px centré. Retirer son `margin-bottom: 24px` propre (l'espacement appartient à la grille de la page, pas au widget).
6. **Masquer les sections vides.** « Habitudes du jour » ne s'affiche que si `habitsState.data.length > 0`. « À vérifier » est déjà conditionnel — garder. Les états de chargement peuvent rester une simple ligne.
7. **Ordre final des sections** (de haut en bas) : En-tête (titre + date + timer compact) → Capture rapide (c'est l'action n°1 d'un assistant, elle mérite le haut de page) → Briefing (résumé + RDV + tâches) → À vérifier (si non vide) → Habitudes (si non vide) → Journal.

## Étape 2 — Cohérence visuelle (fichiers : `App.css`, `index.css`, bloc `STYLES` de `TodayPage.tsx`)

1. **Tuer le `text-align: center` global.** Retirer `text-align: center` de `.app` ; centrer uniquement ce qui doit l'être (`.nav` l'est déjà via `justify-content`). Retirer ensuite les `text-align: left` compensatoires devenus inutiles (`.tasks`, `.files`, `.chat`, `.calendar`, `.briefing`, `.memory-page`, `.search-page`). Vérifier chaque page après ce changement — c'est le changement le plus transversal du plan.
2. **Définir les variables manquantes.** Dans `index.css`, ajouter `--accent` (proposer `#4f46e5`, déjà utilisé par la capture rapide) avec sa variante mode sombre si besoin. Dans le bloc `STYLES` de `TodayPage`, remplacer tous les `var(--border-color, #ccc)`/`#ddd` par `var(--border)` et les couleurs en dur par les variables (`--bg`, `--text`, `--text-h`, `--accent`).
3. **Harmoniser les boutons/cartes.** Les boutons de la capture rapide (fond indigo plein) et de « À vérifier » (vert/rouge pleins) détonnent avec le style neutre bordé du reste. Choisir : bouton primaire = fond `--accent` texte blanc (capture rapide « Envoyer », « Confirmer »), bouton destructif = bordure/texte rouge comme `.task-delete` existant (« Rejeter »). Appliquer partout sur la page.
4. **Largeur et rythme.** `.today-page` garde `max-width: 720px; margin: 0 auto` (bien) ; passer le `gap` à `2rem` entre sections et s'assurer qu'aucun widget n'apporte son propre `margin-bottom` (les retirer de `.session-timer`, `.briefing`).
5. **Français.** Accorder les pluriels du compteur si conservé ailleurs (« 1 tâche », « 1 active ») ; passer tous les `toLocaleString(undefined, …)`/`toLocaleTimeString(undefined, …)` de `TodayPage.tsx`, `DailyBriefing.tsx` et `HealthStatus.tsx` à `'fr-CA'`.

## Étape 3 — Corriger le fonctionnel

1. **Capture rapide non bloquante.** Dans `handleCaptureSubmit` : dès que le POST du message est accepté (`messageRes.ok`), vider le champ et afficher « Envoyé ✓ » ; continuer à drainer le stream **en arrière-plan** (sans `await` bloquant le retour visuel — conserver le drain dans une promesse détachée avec un `catch` silencieux, il reste nécessaire pour que les tool calls du secrétaire s'exécutent).
2. **Rafraîchir après capture.** Une fois le stream réellement terminé (la promesse détachée du point 1), recharger le briefing et les listes (« le secrétaire a peut-être créé une tâche/RDV »). Exposer un `reload()` depuis `useBriefing` s'il n'existe pas, et rappeler aussi le chargement de « À vérifier ».
3. **« À vérifier » rechargeable.** Extraire les deux fetchs du `useEffect` en une fonction `loadReviews()` réutilisable (appelée au mount et après une capture).
4. **Pas de régression backend.** Aucune modif backend requise pour ce plan ; tout se joue dans `frontend/src/`.

## Étape 4 — Vérification (obligatoire avant de conclure)

1. `cd frontend && npm run build` — zéro erreur TypeScript.
2. `npm run dev` + ouvrir l'aperçu : vérifier l'accueil **desktop et mobile** (viewport 375px), **clair et sombre** (`prefers-color-scheme`), aucune erreur console.
3. Vérifier les autres pages après le retrait du `text-align: center` global (Tâches, Calendrier, Chat, Fichiers, Recherche, Mémoire, Habitudes, Contacts, Factures) — c'est là que les régressions sont probables.
4. Tester la capture rapide de bout en bout (le « Envoyé ✓ » doit apparaître en < 1 s même si le LLM est lent ; la liste se rafraîchit ensuite).
5. Captures d'écran avant/après dans la description de PR.

## Contraintes

- Pas de nouvelle dépendance npm (pas de lib UI, pas de lib de data-fetching) — convention du repo.
- Interface en français, comme le reste du portail.
- Ne pas toucher au backend ni aux autres conteneurs.
- Le style « self-contained dans le fichier de page » (bloc `STYLES`) est la convention des pages récentes — le conserver, mais aligné sur les variables CSS globales.
