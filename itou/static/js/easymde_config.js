
let textareas = document.querySelectorAll(".easymde-box");

textareas.forEach((textarea) => {
  new EasyMDE({
    element: textarea,
    autoDownloadFontAwesome: false,
    toolbar: [
      {
        name: "bold",
        action: EasyMDE.toggleBold,
        className: "ri ri-bold ri-lg",
        title: "Gras",
      },
      {
        name: "italic",
        action: EasyMDE.toggleItalic,
        className: "ri ri-italic ri-lg",
        title: "Italique",
      },
      {
        name: "unordered-list",
        action: EasyMDE.toggleUnorderedList,
        className: "ri ri-list-unordered ri-lg",
        title: "Liste à puces",
      },
      {
        name: "ordered-list",
        action: EasyMDE.toggleOrderedList,
        className: "ri ri-list-ordered ri-lg",
        title: "Liste numérotée",
      },
      {
        name: "link",
        action: EasyMDE.drawLink,
        className: "ri ri-link ri-lg",
        title: "Lien",
      },
    ],
    spellChecker: false,
    status: [],
  });
});
