from markdownify.templatetags.markdownify import markdownify


def test_markdown_render_default():
    markdown = "*Lorem ipsum*, **bold** and [link](https://beta.gouv.fr).\n\n- item 1\n- item 2"
    attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'
    assert (
        markdownify(markdown)
        == f'<p><em>Lorem ipsum</em>, <strong>bold</strong> and <a href="https://beta.gouv.fr" {attrs}>link</a>.</p>'
        "\n<ul>\n<li>item 1</li>\n<li>item 2</li>\n</ul>"
    )


def test_markdown_render_default_forbidden_tags():
    markdown = '# Gros titre\n<script></script>\n<span class="font-size:200px;">Gros texte</span>'
    assert markdownify(markdown) == "Gros titre\n\n<p>Gros texte</p>"


def test_markdown_render_inline():
    markdown = "*Lorem ipsum*, **bold** and [link](https://beta.gouv.fr)."
    attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'
    assert (
        markdownify(markdown, "inline")
        == f'<em>Lorem ipsum</em>, <strong>bold</strong> and <a href="https://beta.gouv.fr" {attrs}>link</a>.'
    )


def test_markdown_render_inline_forbidden_tags():
    markdown = '# Gros titre\n<script></script>\n<span class="font-size:200px;">Gros texte</span>\n- item 1\n- item 2'
    assert markdownify(markdown, "inline") == "Gros titre\n\n\nGros texte\n- item 1\n- item 2"
