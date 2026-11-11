const search = document.querySelector("#inventory-search");
document.querySelectorAll(".inventory-slot-icon, .item-icon").forEach(image => {
  function showFallback() {
    image.hidden = true;
    const placeholder = image.parentElement.querySelector(".slot-initial");
    if (placeholder) placeholder.hidden = false;
  }
  image.addEventListener("error", showFallback);
  if (image.complete && !image.naturalWidth) showFallback();
});
if (search) {
  const rows = [...document.querySelectorAll("#inventory-rows tr")];
  const empty = document.querySelector("#no-results");
  search.addEventListener("input", () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    for (const row of rows) {
      const matches = row.textContent.toLocaleLowerCase().includes(query);
      row.hidden = !matches;
      if (matches) visible++;
    }

    empty.hidden = visible !== 0;
  });
}

const augmentPreview = document.querySelector("#augment-preview");
if (augmentPreview) {
  let activeLink = null;
  let closeTimer = null;

  function hidePreview() {
    clearTimeout(closeTimer);
    if (activeLink) activeLink.removeAttribute("aria-describedby");
    activeLink = null;
    augmentPreview.hidden = true;
  }

  function positionPreview() {
    if (!activeLink) return;
    const anchor = activeLink.getBoundingClientRect();
    const box = augmentPreview.getBoundingClientRect();
    const margin = 8;
    const left = Math.max(margin, Math.min(anchor.left, window.innerWidth - box.width - margin));
    const below = anchor.bottom + margin;
    const top = below + box.height <= window.innerHeight - margin ? below :
      Math.max(margin, anchor.top - box.height - margin);
    augmentPreview.style.left = `${left}px`;
    augmentPreview.style.top = `${top}px`;
  }

  function showPreview(link) {
    clearTimeout(closeTimer);
    const template = document.getElementById(`augment-preview-${link.dataset.augmentPreview}`);
    if (!template) return;
    if (activeLink && activeLink !== link) activeLink.removeAttribute("aria-describedby");
    activeLink = link;
    augmentPreview.replaceChildren(template.content.cloneNode(true));
    augmentPreview.querySelectorAll("img").forEach(image => {
      image.addEventListener("error", () => { image.hidden = true; });
    });
    augmentPreview.hidden = false;
    link.setAttribute("aria-describedby", "augment-preview");
    positionPreview();
  }

  function scheduleClose() {
    clearTimeout(closeTimer);
    closeTimer = setTimeout(hidePreview, 150);
  }

  document.querySelectorAll("[data-augment-preview]").forEach(link => {
    link.addEventListener("mouseenter", () => showPreview(link));
    link.addEventListener("focus", () => showPreview(link));
    link.addEventListener("mouseleave", () => {
      if (document.activeElement !== link) scheduleClose();
    });
    link.addEventListener("blur", scheduleClose);
    link.addEventListener("click", hidePreview);
  });
  augmentPreview.addEventListener("mouseenter", () => clearTimeout(closeTimer));
  augmentPreview.addEventListener("mouseleave", () => {
    if (document.activeElement !== activeLink) scheduleClose();
  });
  document.addEventListener("keydown", event => { if (event.key === "Escape") hidePreview(); });
  window.addEventListener("resize", positionPreview);
  window.addEventListener("scroll", positionPreview, true);
}

const screenshotDialog = document.querySelector("#item-screenshot-dialog");
if (screenshotDialog && typeof screenshotDialog.showModal === "function") {
  const image = document.querySelector("#item-screenshot-image");
  const title = document.querySelector("#item-screenshot-title");
  const details = document.querySelector("#item-screenshot-details");
  const error = document.querySelector("#item-screenshot-error");
  image.addEventListener("error", () => { error.hidden = false; image.hidden = true; });
  document.querySelectorAll("[data-item-screenshot]").forEach(link => {
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      title.textContent = link.dataset.itemName;
      image.alt = `Saved screenshot of ${link.dataset.itemName}`;
      image.hidden = false;
      error.hidden = true;
      image.src = link.dataset.itemScreenshot;
      details.href = link.href;
      screenshotDialog.showModal();
    });
  });
  document.querySelector("#close-item-screenshot").addEventListener("click", () => screenshotDialog.close());
}
