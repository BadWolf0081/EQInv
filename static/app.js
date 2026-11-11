const search = document.querySelector("#inventory-search");
document.querySelectorAll(".inventory-slot-icon, .item-icon").forEach(image => {
  image.addEventListener("error", () => { image.hidden = true; });
  if (image.complete && !image.naturalWidth) image.hidden = true;
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
