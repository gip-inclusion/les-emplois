// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10420-14449
// source=les-emplois itou/templates/layout/_header_authenticated.html (#offcanvasNav, displayed as a sidebar on large screens under body.l-authenticated)
// component=Menu Connecté
const figma = require('figma')

export default {
  example: figma.html`{# Rendered by layout/base.html through layout/_header_authenticated.html for authenticated users #}
<div class="offcanvas" id="offcanvasNav" aria-label="Barre de navigation principale">
    <div class="offcanvas-header offcanvas-header--organization">
        <div class="dropdown dropdown-organization flex-grow-1 py-4">{% organization_switcher mode="mobile" %}</div>
        <div class="border-start border-nuance-08 d-xl-none">
            <button type="button" class="btn-link ps-4 pt-5 pe-2 me-n2" data-bs-dismiss="offcanvas" aria-label="Fermer">
                <i class="ri-close-line" aria-hidden="true"></i>
            </button>
        </div>
    </div>
    <div class="offcanvas-body d-flex flex-column">
        <nav class="flex-grow-1" role="navigation" aria-label="Navigation principale">
            {% nav request %}
        </nav>
        <div class="dropup dropup-center">
            <button type="button" class="btn btn-outline-primary btn-ico btn-block bg-white dropdown-toggle my-3" data-bs-toggle="dropdown" aria-haspopup="true" aria-controls="dashboardUserDropdownMobile" aria-expanded="false">
                <i class="ri-account-circle-line" aria-hidden="true"></i>
                <span class="ms-2">Mon espace</span>
            </button>
            <div class="dropdown-menu" id="dashboardUserDropdownMobile">…</div>
        </div>
        <div class="dropup dropup-center">
            <button type="button" class="btn btn-link btn-block dropdown-toggle p-0" data-bs-toggle="dropdown" aria-haspopup="true" aria-controls="helpDropdownMobile" aria-expanded="false">Besoin d'aide ?</button>
            <div class="dropdown-menu" id="helpDropdownMobile">…</div>
        </div>
    </div>
    <div class="offcanvas-footer flex-column align-items-stretch">
        <div class="offcanvas-footer__legal">
            <div class="d-none d-xl-block">
                <img src="{% static_theme_images 'logo-plateforme-inclusion.svg' %}" alt="{% brand %}" height="50">
            </div>
            <ul>…</ul>
        </div>
    </div>
</div>`,
  id: 'connected-menu',
  metadata: { nestable: true },
}
