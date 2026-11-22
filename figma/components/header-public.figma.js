// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14632-1436
// source=les-emplois itou/templates/layout/_header.html (included by layout/base.html when the user is not authenticated)
// component=Header Deconnecté
const figma = require('figma')

export default {
  example: figma.html`{# Rendered by layout/base.html for anonymous users — never include it by hand #}
{% include "layout/_header.html" %}

<header role="banner" id="header">
    <section class="s-header">
        <div class="s-header__container container">
            <div class="s-header__row row">
                <div class="s-header__col s-header__col--logo-ministere col col-md-auto d-flex align-items-center pe-0">
                    <a href="{% url 'home:hp' %}" class="s-header__logo-ministere">
                        <img src="{% static_theme_images 'logo-republique-francaise.svg' %}" alt="Rébublique Française">
                    </a>
                </div>
                <div class="s-header__col s-header__col--logo-service col-auto d-flex align-items-center px-0">
                    <a href="{% url 'home:hp' %}">
                        <img src="{% static_theme_images 'logo-plateforme-inclusion.svg' %}" height="90" alt="{% brand %}">
                    </a>
                </div>
                <div class="s-header__col s-header__col--nav col d-none d-lg-inline-flex d-lg-flex align-items-center justify-content-end pe-0 pe-xl-3">
                    <nav role="navigation" id="nav-primary" aria-label="Navigation principale">
                        <ul>
                            <li class="d-none d-xl-inline-block dropdown">
                                <button type="button" class="btn btn-link dropdown-toggle mh-auto p-0" data-bs-toggle="dropdown" aria-haspopup="true" aria-controls="helpDropdown" aria-expanded="false">Besoin d’aide ?</button>
                                <div class="dropdown-menu" id="helpDropdown">…</div>
                            </li>
                            <li>
                                <a class="btn btn-ico btn-outline-primary" href="{% url "signup:choose_user_kind" %}">
                                    <i class="ri-user-add-line" aria-hidden="true"></i>
                                    <span>S’inscrire</span>
                                </a>
                            </li>
                            <li class="dropdown dropdown-login">
                                <a href="{% url 'account_login' %}{% redirection_url redirect_field_value|default:"" %}" class="btn btn-ico btn-primary">
                                    <i class="ri-login-box-line" aria-hidden="true"></i>
                                    <span>Se connecter</span>
                                </a>
                            </li>
                        </ul>
                    </nav>
                </div>
                <div class="s-header__col s-header__col--burger col col-lg-auto d-flex align-items-center justify-content-end d-xl-none ps-0">
                    <button type="button" class="btn btn-link btn-ico pe-0" data-bs-toggle="offcanvas" data-bs-target="#offcanvasNav" aria-controls="offcanvasNav" aria-label="Ouvrir le menu de navigation principale pour mobile">
                        <i class="ri-menu-line" id="open" aria-hidden="true"></i>
                        <span>Menu</span>
                    </button>
                </div>
            </div>
        </div>
    </section>
    <div class="offcanvas" id="offcanvasNav" aria-label="Navigation principale pour mobile">…</div>
</header>`,
  id: 'header-public',
  metadata: { nestable: true },
}
