"""The icon of a fact in the « Prochaines étapes » side drawers, from its label: one meaning, one icon, everywhere."""

from django import template


register = template.Library()

# Remix icons, by the first keyword found in the label (lowercased, after a space: " le" is a word): the more
# specific first.
FACT_ICONS = [
    ("publics", "ri-group-line"),
    ("frais", "ri-money-euro-circle-line"),
    ("adresse", "ri-map-pin-line"),
    ("accueil", "ri-door-open-line"),
    ("employeur", "ri-building-line"),
    ("prescripteur", "ri-user-line"),
    ("usager", "ri-user-line"),
    ("émetteur", "ri-user-line"),
    ("destinataire", "ri-mail-send-line"),
    ("e-mail", "ri-mail-line"),
    ("numéro", "ri-hashtag"),
    ("téléphone", "ri-phone-line"),
    ("message", "ri-message-2-line"),
    ("motifs du refus", "ri-close-circle-line"),
    ("motif", "ri-chat-quote-line"),
    ("explication", "ri-chat-quote-line"),
    ("reliquat", "ri-hourglass-line"),
    ("reste", "ri-hourglass-line"),
    ("poste", "ri-briefcase-line"),
    ("critère", "ri-shield-check-line"),
    ("frein", "ri-error-warning-line"),
    ("autonomie", "ri-compass-3-line"),
    ("solution", "ri-flag-line"),
    ("orientation", "ri-signpost-line"),
    ("service", "ri-community-line"),
    ("action préalable", "ri-task-line"),
    ("suspension", "ri-pause-circle-line"),
    ("prolongation", "ri-refresh-line"),
    ("contrat", "ri-file-text-line"),
    ("candidature du", "ri-calendar-line"),
    ("candidature", "ri-file-user-line"),
    ("période", "ri-calendar-line"),
    ("date", "ri-calendar-line"),
    ("depuis", "ri-calendar-line"),
    ("jusqu", "ri-calendar-line"),
    (" fin", "ri-calendar-close-line"),
    ("début", "ri-calendar-line"),
    (" le", "ri-calendar-line"),
    ("déclaré", "ri-calendar-line"),
    ("structure", "ri-building-line"),
    ("organisation", "ri-building-line"),
    ("chez", "ri-building-line"),
    (" par", "ri-user-line"),
]
DEFAULT_ICON = "ri-information-line"


@register.filter
def fact_icon(label):
    """The icon of a fact, from its label: "Date de début" a calendar, "Structure" a building..."""
    text = f" {str(label).lower()}"
    return next((icon for keyword, icon in FACT_ICONS if keyword in text), DEFAULT_ICON)
