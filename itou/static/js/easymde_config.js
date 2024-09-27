
let textareas = document.querySelectorAll(".easymde-box");

textareas.forEach((textarea) => {
  const easyMDE = new EasyMDE({
    element: textarea,
    toolbar: [
      {
        name: "bold",
        action: EasyMDE.toggleBold,
        className: "ri-bold",
        title: "Gras",
      },
      {
        name: "italic",
        action: EasyMDE.toggleItalic,
        className: "ri-italic",
        title: "Italique",
      },
      {
        name: "unordered-list",
        action: EasyMDE.toggleUnorderedList,
        className: "ri-list-unordered",
        title: "Liste",
      },
      {
        name: "link",
        action: EasyMDE.drawLink,
        className: "ri-link",
        title: "Lien",
      },
    ],
    spellChecker: false,
    status: [],
  });
});
