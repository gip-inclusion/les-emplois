// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=11204-3106
// source=les-emplois itou/templates/layout/_header.html (Connecté=Off) and layout/_header_authenticated.html (Connecté=On), #offcanvasNav
// component=Menu Mobile / Non connecté
const figma = require('figma')
const instance = figma.selectedInstance

const connected = instance.getEnum('Connecté', { On: true, Off: false })

let example
if (connected) {
  example = figma.html`{# layout/_header_authenticated.html — opened by the "Menu" burger button #}
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
</div>`
} else {
  example = figma.html`{# layout/_header.html — opened by the "Menu" burger button #}
<div class="offcanvas" id="offcanvasNav" aria-label="Navigation principale pour mobile">
    <div class="offcanvas-header">
        <h4 class="h5 mb-0 btn-ico align-items-center" id="offcanvasApplyFiltersLabel">
            <i class="ri-menu-line" aria-hidden="true"></i>
            <span>Menu</span>
        </h4>
        <button type="button" class="btn-link px-2 me-n2" data-bs-dismiss="offcanvas" aria-label="Fermer">
            <i class="ri-close-line" aria-hidden="true"></i>
        </button>
    </div>
    <div class="offcanvas-footer flex-column align-items-stretch">
        <nav role="navigation" aria-label="Menu de navigation principale pour mobile">
            <div class="dropup-center dropdown-login">
                <a href="{% url 'account_login' %}{% redirection_url redirect_field_value|default:"" %}" class="btn btn-block btn-ico btn-primary">
                    <i class="ri-login-box-line" aria-hidden="true"></i>
                    <span>Se connecter</span>
                </a>
            </div>
            <a class="btn btn-block btn-ico btn-outline-primary my-3" href="{% url "signup:choose_user_kind" %}">
                <i class="ri-user-add-line" aria-hidden="true"></i>
                <span>S’inscrire</span>
            </a>
            <div class="dropup dropup-center">
                <button type="button" class="btn btn-link btn-block dropdown-toggle p-0" data-bs-toggle="dropdown" aria-haspopup="true" aria-controls="helpDropdownMobile" aria-expanded="false">Besoin d’aide ?</button>
                <div class="dropdown-menu" id="helpDropdownMobile">…</div>
            </div>
        </nav>
    </div>
</div>`
}

export default {
  example,
  id: 'mobile-menu',
  metadata: { nestable: true },
}
