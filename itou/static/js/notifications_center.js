htmx.onLoad((target) => {
  const allNotifications = document.getElementById("id_notifications-all");
  const form = allNotifications.closest("form");
  updateAllNotifications();

  function childrenNotificationsSelected(container) {
    return !container.querySelectorAll("input.notification-checkbox:not(:checked)").length;
  }

  function updateAllNotifications() {
    allNotifications.checked = childrenNotificationsSelected(form);
  }

  function toggleCollapse(collapse, force) {
    const collapseController = bootstrap.Collapse.getOrCreateInstance(collapse, { toggle: false });
    if (force === undefined) {
      collapseController.toggle();
    } else if (force === true) {
      collapseController.show();
    } else {
      throw new Error("Not implemented");
    }
  }

  form.addEventListener("change", (event) => {
    if (event.target === allNotifications) {
      form.querySelectorAll("input[type=checkbox]").forEach((input) => {
        input.checked = event.target.checked;
      });
      if (!event.target.checked) {
        form.querySelectorAll(".collapse").forEach((collapse) => toggleCollapse(collapse, true));
      }
    } else if (event.target.classList.contains("category-grouper")) {
      const categoryGroup = event.target.closest(".notification-collapse");
      categoryGroup.querySelectorAll("input.notification-checkbox").forEach((notification) => {
        notification.checked = event.target.checked;
      });
    }

    updateAllNotifications();
    const collapseGroup = event.target.closest(".notification-collapse");
    if (collapseGroup) {
      collapseGroup.querySelector(".category-grouper").checked = childrenNotificationsSelected(collapseGroup);
    }
  });

  document.getElementsByClassName("notification-collapse").forEach((collapseGroup) => {
    const collapseToggle = collapseGroup.querySelector("a[aria-controls]");
    collapseToggle.addEventListener("click", (event) => {
      toggleCollapse(collapseGroup.querySelector(".collapse"));
    });
    const collapsibleElement = collapseGroup.querySelector(".collapse");
    collapsibleElement.addEventListener("hide.bs.collapse", () => {
      collapseToggle.ariaExpanded = "false";
    });
    collapsibleElement.addEventListener("show.bs.collapse", () => {
      collapseToggle.ariaExpanded = "true";
    });
  });

  if (!allNotifications.checked) {
    document.getElementsByClassName("notification-collapse").forEach((collapseGroup) => {
      toggleCollapse(collapseGroup.querySelector(".collapse"), true);
    });
  }
});
