// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14632-1502
// source=les-emplois itou/templates/layout/_footer.html + layout/_footer_legal_content.html (included by layout/base.html for anonymous users)
// component=Footer
const figma = require('figma')
const instance = figma.selectedInstance

// Only the Emplois footer lives in les-emplois. Communauté, Marché and Pilotage
// are separate products: they reuse the same itou-theme sections
// (.s-footer-quick / .s-footer-gip / .s-footer-legal) with their own links.
const service = instance.getEnum('Service', {
  Communauté: 'communaute',
  Emplois: 'emplois',
  Marché: 'marche',
  Pilotage: 'pilotage',
})
// Desktop and Mobile are the same markup: the Bootstrap grid (col-12 col-md-6 col-lg-auto) stacks the columns.
instance.getEnum('Device', { Desktop: 'desktop', Mobile: 'mobile' })

const otherService = {
  communaute: 'La communauté',
  marche: 'Le marché',
  pilotage: 'Le pilotage',
}[service]

let example
if (otherService) {
  example = figma.html`{# ${otherService} de l’inclusion : footer maintained outside les-emplois, same itou-theme sections #}
<footer role="contentinfo" id="footer">
    <section class="s-footer-quick">…</section>
    <section class="s-footer-gip">…</section>
    <section class="s-footer-legal">…</section>
</footer>`
} else {
  example = figma.html`{# Rendered by layout/base.html for anonymous users — never include it by hand #}
{% include "layout/_footer.html" %}

<footer role="contentinfo" id="footer">
    <section class="s-footer-quick">
        <div class="s-footer-quick__container container">
            <div class="s-footer-quick__row row">
                <div class="s-footer-quick__col col-12 col-md-6 col-lg-auto">
                    <strong>Accès rapides</strong>
                    <ul>
                        <li><a href="{% url 'search:home' %}">Accueil</a></li>
                        <li><a href="{% url 'releases:list' %}">Journal des modifications</a></li>
                    </ul>
                </div>
                <div class="s-footer-quick__col col-12 col-md-6 col-lg-auto">
                    <strong>Besoin d'aide ?</strong>
                    <ul>…</ul>
                </div>
                <div class="s-footer-quick__col col-12 col-lg-auto">
                    <strong>Réseaux sociaux</strong>
                    <ul>…</ul>
                </div>
            </div>
        </div>
    </section>
    <section class="s-footer-gip">
        <div class="s-footer-gip__container container">
            <div class="s-footer-gip__row row">
                <div class="s-footer-gip__col s-footer-gip__col--logo col-12 col-md-6 col-lg-auto">…</div>
                <div class="s-footer-gip__col col-12 col-md-6 col-lg">
                    <p class="mb-1"><strong>Ce service fait partie de La plateforme de l’inclusion</strong></p>
                    <p class="m-0">…</p>
                </div>
                <div class="s-footer-gip__col s-footer-gip__col--links col-12 col-lg-auto">
                    <ul>…</ul>
                </div>
            </div>
        </div>
    </section>
    <section class="s-footer-legal">
        <div class="s-footer-legal__container container">{% include "layout/_footer_legal_content.html" %}</div>
    </section>
</footer>`
}

export default {
  example,
  id: 'footer',
  metadata: { nestable: true },
}
