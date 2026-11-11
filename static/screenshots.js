"use strict";

(() => {
  const root = document.getElementById("importer");
  const items = JSON.parse(document.getElementById("inventory-items").textContent);
  const file = document.getElementById("screenshot-file");
  const area = document.getElementById("crop-area");
  const container = document.getElementById("crop-image");
  const source = document.getElementById("source-image");
  const selection = document.getElementById("selection");
  const coords = ["crop-x", "crop-y", "crop-width", "crop-height"].map(id => document.getElementById(id));
  const recognize = document.getElementById("recognize");
  const status = document.getElementById("status");
  const review = document.getElementById("review");
  const iconSelector = document.querySelector(".icon-selector");
  const preview = iconSelector.querySelector(".icon-source img");
  const itemSelect = document.getElementById("item-select");
  const matchHelp = document.getElementById("match-help");
  const suggestions = document.getElementById("name-suggestions");
  const suggestionButtons = document.getElementById("suggestion-buttons");
  const distillerWarning = document.getElementById("distiller-warning");
  const types = document.getElementById("types");
  const stats = document.getElementById("stats");
  const raw = document.getElementById("raw-text");
  const saveStats = document.getElementById("save-stats");
  const confirmed = document.getElementById("confirmed");
  let sourceUrl = null;
  let previewUrl = null;
  let crop = null;
  let start = null;
  let busy = false;

  function message(text, isError = false) {
    status.textContent = text;
    status.className = "notice" + (isError ? " error" : "");
    status.hidden = !text;
  }

  function clearReview() {
    review.hidden = true;
    crop = null;
    confirmed.checked = false;
    iconSelector.dispatchEvent(new Event("clear-icon"));
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    preview.removeAttribute("src");
  }

  function setBusy(value) {
    busy = value;
    file.disabled = value;
    recognize.disabled = value;
    coords.forEach(input => { input.disabled = value; });
    review.querySelectorAll("input, select, textarea, button").forEach(input => { input.disabled = value; });
  }

  function readBox() {
    if (coords.some(input => input.value === "")) return null;
    const values = coords.map(input => Number(input.value));
    const [x, y, width, height] = values;
    if (!values.every(Number.isSafeInteger) || x < 0 || y < 0 || width < 1 || height < 1 ||
        x + width > source.naturalWidth || y + height > source.naturalHeight) return null;
    return {x, y, width, height};
  }

  function showBox() {
    const box = readBox();
    selection.hidden = !box;
    if (!box) return;
    selection.style.left = `${100 * box.x / source.naturalWidth}%`;
    selection.style.top = `${100 * box.y / source.naturalHeight}%`;
    selection.style.width = `${100 * box.width / source.naturalWidth}%`;
    selection.style.height = `${100 * box.height / source.naturalHeight}%`;
  }

  function point(event) {
    const rect = source.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(source.naturalWidth, Math.round((event.clientX - rect.left) * source.naturalWidth / rect.width))),
      y: Math.max(0, Math.min(source.naturalHeight, Math.round((event.clientY - rect.top) * source.naturalHeight / rect.height)))
    };
  }

  function updateDrag(event) {
    const end = point(event);
    const values = [Math.min(start.x, end.x), Math.min(start.y, end.y),
      Math.abs(start.x - end.x), Math.abs(start.y - end.y)];
    coords.forEach((input, index) => { input.value = values[index]; });
    showBox();
  }

  file.addEventListener("change", () => {
    clearReview();
    area.hidden = true;
    selection.hidden = true;
    coords.forEach(input => { input.value = ""; });
    message("");
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    sourceUrl = null;
    const chosen = file.files[0];
    if (!chosen) return;
    if (!["image/png", "image/jpeg"].includes(chosen.type) || chosen.size > 10 * 1024 * 1024) {
      message("Choose a PNG or JPEG screenshot no larger than 10 MB.", true);
      return;
    }
    sourceUrl = URL.createObjectURL(chosen);
    source.onload = () => {
      if (source.naturalWidth * source.naturalHeight > 20000000) {
        message("Screenshot exceeds the 20 megapixel limit.", true);
        return;
      }
      area.hidden = false;
    };
    source.onerror = () => message("Unable to read this image.", true);
    source.src = sourceUrl;
  });

  container.addEventListener("pointerdown", event => {
    if (busy || event.button !== 0) return;
    event.preventDefault();
    clearReview();
    message("");
    start = point(event);
    container.setPointerCapture(event.pointerId);
    updateDrag(event);
  });
  container.addEventListener("pointermove", event => { if (start) updateDrag(event); });
  container.addEventListener("pointerup", event => {
    if (!start) return;
    updateDrag(event);
    start = null;
  });
  container.addEventListener("pointercancel", () => { start = null; });
  coords.forEach(input => input.addEventListener("input", () => {
    clearReview();
    showBox();
  }));

  async function post(url, form) {
    const response = await fetch(url, {method: "POST", body: form});
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) throw new Error("Server returned an unexpected response. Check the server logs.");
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Request failed.");
    return result;
  }

  function containsItemName(text, name) {
    let position = text.indexOf(name);
    while (position !== -1) {
      const before = text[position - 1] || "";
      const after = text[position + name.length] || "";
      if (!/[\p{L}\p{N}]/u.test(before) && !/[\p{L}\p{N}]/u.test(after)) return true;
      position = text.indexOf(name, position + 1);
    }
    return false;
  }

  recognize.addEventListener("click", async () => {
    clearReview();
    const box = readBox();
    if (!box) {
      message("Select a valid rectangle within the screenshot.", true);
      return;
    }
    setBusy(true);
    message("Recognizing this item window...");
    try {
      const canvas = document.createElement("canvas");
      canvas.width = box.width;
      canvas.height = box.height;
      canvas.getContext("2d").drawImage(source, box.x, box.y, box.width, box.height, 0, 0, box.width, box.height);
      crop = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
      if (!crop) throw new Error("Unable to create the crop.");
      const form = new FormData();
      form.append("csrf_token", root.dataset.csrf);
      form.append("screenshot", crop, "item.png");
      const result = await post(root.dataset.recognizeUrl, form);
      previewUrl = URL.createObjectURL(crop);
      preview.src = previewUrl;
      stats.value = JSON.stringify(result.stats, null, 2);
      types.value = result.types.join("|");
      raw.value = result.raw_text;
      saveStats.checked = true;
      const text = result.raw_text.toLocaleLowerCase().replace(/\s+/g, " ");
      const matches = items.filter(item => containsItemName(text, item.name.toLocaleLowerCase().replace(/\s+/g, " ")));
      itemSelect.value = matches.length === 1 ? String(matches[0].index) : "";
      suggestionButtons.replaceChildren();
      const options = matches.length === 1 ? [] : result.name_suggestions;
      suggestions.hidden = options.length === 0;
      for (const item of options) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = `${item.name} (#${item.id})`;
        button.addEventListener("click", () => {
          itemSelect.value = String(item.index);
          matchHelp.textContent = "Possible match selected. Verify it against the screenshot.";
        });
        suggestionButtons.appendChild(button);
      }
      matchHelp.textContent = matches.length === 1
        ? `Suggested from OCR: ${matches[0].name} (#${matches[0].id}). Verify before saving.`
        : "No unique exact-name match. Select the correct item; possible matches are not verified.";
      const roman = /^(?:X{0,2}(?:IX|IV|V?I{0,3})|XXX)$/;
      const distiller = result.stats.distiller_class;
      const invalid = distiller && distiller !== "Perfected only" && !roman.test(distiller);
      distillerWarning.hidden = !invalid;
      distillerWarning.textContent = invalid
        ? `OCR read distiller class "${distiller}", which is not a valid class from I to XXX. Check the image and correct or remove distiller_class before saving.`
        : "";
      review.hidden = false;
      message("Compare the crop and every suggested value before saving.");
    } catch (error) {
      clearReview();
      message(error.message, true);
    } finally {
      setBusy(false);
    }
  });

  review.addEventListener("submit", async event => {
    event.preventDefault();
    if (!crop || !confirmed.checked || !itemSelect.value) {
      message("Select an item and confirm your review before saving.", true);
      return;
    }
    setBusy(true);
    message("Saving this item...");
    try {
      const form = new FormData();
      form.append("csrf_token", root.dataset.csrf);
      form.append("row_index", itemSelect.value);
      form.append("screenshot", crop, "item.png");
      form.append("confirmed", "yes");
      if (saveStats.checked) form.append("save_stats", "yes");
      form.append("stats_json", stats.value);
      form.append("types", types.value);
      form.append("raw_text", raw.value);
      for (const input of iconSelector.querySelectorAll("input")) {
        form.append(input.name, input.value);
      }
      const result = await post(root.dataset.saveUrl, form);
      clearReview();
      message(`${result.message} Select the next window, or open the item from the inventory.`);
    } catch (error) {
      message(error.message, true);
    } finally {
      setBusy(false);
    }
  });
})();
