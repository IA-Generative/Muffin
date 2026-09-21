# Composer du chat — dictée vocale

Documente la fonctionnalité de dictée vocale du composer de chat, pour servir de référence à un
agent capable d'interagir avec l'UI. Suit la même logique que [`docs/ui/admin/`](../admin/README.md) -
un sous-dossier par page/fonctionnalité.

Composant Vue : [`frontend/src/components/ChatWindow.vue`](../../../frontend/src/components/ChatWindow.vue).
Composable : [`frontend/src/composables/useVoiceInput.ts`](../../../frontend/src/composables/useVoiceInput.ts).

## Ce que c'est

Accessibilité (issue #108) : un bouton micro dans le composer permet de dicter un message au lieu
de le taper, en s'appuyant sur la transcription native du navigateur (Web Speech API -
`SpeechRecognition`/`webkitSpeechRecognition`), sans passer par un service de transcription côté
serveur.

Voir [`screenshots/voice-input-idle.png`](screenshots/voice-input-idle.png) - bouton micro au repos,
juste avant le bouton d'envoi.

## Support navigateur

`SpeechRecognition` n'est bien supporté que sur Chrome/Edge desktop ; Firefox et Safari ne
l'implémentent pas. Le bouton micro (`.chat-window__mic`) n'est rendu du tout que si
`useVoiceInput().isSupported` est vrai (`v-if`, pas juste désactivé) - sur un navigateur non
supporté, il n'apparaît pas et un message de préconisation s'affiche à la place sous le composer
(`.chat-window__voice-hint`) : "La dictée vocale n'est pas disponible sur ce navigateur - utilisez
Google Chrome ou Microsoft Edge...".

## Utilisation

- **Bouton micro** (`aria-pressed`, `aria-label` dynamique) : clic pour démarrer/arrêter la
  dictée. État actif visuellement distinct (fond rouge, icône qui pulse via CSS `animation`).
- **Raccourci clavier global : `Alt+Maj+V`** (`aria-keyshortcuts="Alt+Shift+V"` sur le bouton,
  mentionné dans son `title`/`aria-label`). Écouteur attaché sur `window` (pas seulement sur le
  textarea) - fonctionne depuis n'importe où dans la page, pas seulement quand le focus est dans
  le composer, pour qu'un utilisateur naviguant au clavier/lecteur d'écran puisse démarrer la
  dictée sans devoir d'abord tabuler jusqu'au champ de texte.
- Pendant l'écoute, le texte transcrit s'ajoute en direct au brouillon existant (résultats
  intermédiaires affichés au fur et à mesure, pas seulement à la fin d'une phrase) - il ne
  remplace jamais ce qui a déjà été tapé ou dicté avant.
- Erreur de permission micro refusée (ou tout autre échec de reconnaissance) : message d'erreur
  explicite dans le même emplacement que le message de préconisation
  (`.chat-window__voice-hint--error`, `role="alert"`), jamais un échec silencieux.

## Comportement notable pour un agent qui pilote l'UI

- Le clic ou le raccourci ne fait *que* démarrer/arrêter la capture micro - il n'envoie jamais le
  message automatiquement. L'envoi reste un geste explicite (bouton "Envoyer" ou Entrée).
- `SpeechRecognition.start()` déclenche la demande de permission micro du navigateur si elle n'a
  pas encore été accordée pour l'origine - dans un contexte automatisé (Playwright/CDP), il faut
  accorder la permission au préalable (`context.grantPermissions(['microphone'], { origin })`) et
  lancer Chrome avec `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream` pour
  éviter un prompt bloquant et simuler un micro.
