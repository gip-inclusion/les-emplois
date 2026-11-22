// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10420-14455
// source=les-emplois itou/templates/layout/_header_authenticated.html (#offcanvasNav: end of .offcanvas-body + .offcanvas-footer)
// component=Bas
const figma = require('figma')

export default {
  example: figma.html`<div class="dropup dropup-center">
    <button type="button"
            class="btn btn-outline-primary btn-ico btn-block bg-white dropdown-toggle my-3"
            data-bs-toggle="dropdown"
            aria-haspopup="true"
            aria-controls="dashboardUserDropdownMobile"
            aria-expanded="false">
        <i class="ri-account-circle-line" aria-hidden="true"></i>
        <span class="ms-2">Mon espace</span>
    </button>
    <div class="dropdown-menu" id="dashboardUserDropdownMobile">
        {% include "layout/_header_user_dropdown_menu.html" with request=request user=user mobile=True csrf_token=csrf_token only %}
    </div>
</div>
<div class="dropup dropup-center">
    <button type="button"
            class="btn btn-link btn-block dropdown-toggle p-0"
            data-bs-toggle="dropdown"
            aria-haspopup="true"
            aria-controls="helpDropdownMobile"
            aria-expanded="false">Besoin d'aide ?</button>
    <div class="dropdown-menu" id="helpDropdownMobile">
        {% include "layout/_header_help_dropdown_content.html" with user=user request=request ITOU_HELP_CENTER_URL=ITOU_HELP_CENTER_URL only %}
    </div>
</div>
…
<div class="offcanvas-footer flex-column align-items-stretch">
    <div class="offcanvas-footer__legal">
        <div class="d-none d-xl-block">
            <img src="{% static_theme_images 'logo-plateforme-inclusion.svg' %}" alt="{% brand %}" height="50">
        </div>
        <ul>
            <li><a href="{% url 'accessibility' %}">Accessibilité : partiellement conforme</a></li>
            <li><a href="https://github.com/gip-inclusion/les-emplois" rel="noopener" target="_blank">Code source</a></li>
            <li><a href="{% static 'pdf/syntheseSecurite.pdf' %}" rel="noopener" target="_blank">Homologation sécurité</a></li>
            <li><a href="{% url 'legal-notice' %}">Mentions légales</a></li>
            <li><a href="{% url 'legal-privacy' %}">Confidentialité</a></li>
            <li><a href="{% url 'legal-terms' %}">CGU</a></li>
        </ul>
    </div>
</div>`,
  id: 'connected-menu-bottom',
  metadata: { nestable: true },
}
