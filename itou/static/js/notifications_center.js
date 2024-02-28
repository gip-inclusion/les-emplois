htmx.onLoad((target) => {
  /**
   * JS to handle checkboxes
   **/

  let notificationGroups = [];
  let notificationsContainer = document.querySelector("#id_notifications");
  let mainNotificationsInputElement = document.querySelector("#id_notifications-all");

  handleMainNotificationsInputChange = function () {
    notificationsContainer.querySelectorAll("input.wrapping-checkbox").forEach((input) => {
      input.checked = mainNotificationsInputElement.checked;
    });

    notificationsContainer.querySelectorAll("input.notification-checkbox").forEach((input) => {
      input.checked = mainNotificationsInputElement.checked;
    });

    notificationGroups.forEach(function (group) {
      group.hide() ? mainNotificationsInputElement.checked : group.show();
    });
  };

  checkAllChecked = function () {
    mainNotificationsInputElement.checked = Boolean(
      !notificationsContainer.querySelectorAll("input.notification-checkbox:not(:checked)").length
    );

    if (!mainNotificationsInputElement.checked) {
      notificationGroups.forEach((group) => {
        group.show();
      });
    }
  };

  class NotificationGroup {
    constructor(container) {
      this.container = container;
      this.titleElement = this.container.firstElementChild;
      this.collapsibleElement = this.titleElement.nextElementSibling;
      this.allNotificationsInputElement = this.collapsibleElement.querySelector("input.wrapping-checkbox");
      this.notificationsInputElements = this.collapsibleElement.querySelectorAll(
        ".category-notifications input.notification-checkbox"
      );

      this.collapseInstance = bootstrap.Collapse.getOrCreateInstance(this.collapsibleElement, {
        toggle: false,
      });

      this.titleElement.addEventListener("click", () => {
        this.toggle();
      });

      this.allNotificationsInputElement.addEventListener("click", () => {
        this.onAllClick();
      });

      this.notificationsInputElements.forEach((input) => {
        input.addEventListener("click", () => {
          this.onIndividualClick(input);
        });
      });

      this.collapsibleElement.addEventListener("hide.bs.collapse", () => {
        this.onHide();
      });

      this.collapsibleElement.addEventListener("show.bs.collapse", () => {
        this.onShow();
      });
    }

    show() {
      this.collapseInstance.show();
    }

    hide() {
      this.collapseInstance.hide();
    }

    toggle() {
      this.collapseInstance.toggle();
    }

    isAllChecked() {
      for (let input of this.notificationsInputElements) {
        if (!input.checked) {
          return false;
        }
      }
      return true;
    }

    checkAllChecked() {
      this.allNotificationsInputElement.checked = this.isAllChecked();
      checkAllChecked();
    }

    onShow() {
      this.titleElement.setAttribute("aria-expanded", true);
    }

    onHide() {
      this.titleElement.setAttribute("aria-expanded", false);
    }

    onAllClick() {
      this.notificationsInputElements.forEach((input) => {
        input.checked = this.allNotificationsInputElement.checked;
      });
      if (this.allNotificationsInputElement.checked) {
        checkAllChecked();
      } else {
        mainNotificationsInputElement.checked = false;
      }
    }

    onIndividualClick(input) {
      this.checkAllChecked();
    }
  }

  target.querySelectorAll(".notification-collapse").forEach((element) => {
    notificationGroups.push(new NotificationGroup(element));
  });

  mainNotificationsInputElement.addEventListener("change", () => {
    handleMainNotificationsInputChange();
  });

  checkAllChecked();
});
