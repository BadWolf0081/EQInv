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
  const observationPanel = document.getElementById("observation-panel");
  const observationSlots = document.getElementById("observation-slots");
  const verifyObservation = document.getElementById("verify-observation");
  const overwritePrompt = document.getElementById("overwrite-prompt");
  const overwriteMessage = document.getElementById("overwrite-message");
  const overwriteChanges = document.getElementById("overwrite-changes");
  let overwriteToken = "";
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
    verifyObservation.checked = false;
    overwriteToken = "";
    overwritePrompt.hidden = true;
    observationPanel.hidden = true;
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
    if (!response.ok) {
      const error = new Error(result.error || "Request failed.");
      error.conflict = result.conflict;
      throw error;
    }
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

  function updateObservation() {
    verifyObservation.checked = false;
    const item = items.find(entry => String(entry.index) === itemSelect.value);
    observationPanel.hidden = !item || !item.is_equipment;
    observationSlots.replaceChildren();
    if (!item || !item.is_equipment) return;
    if (!item.children.length) {
      const line = document.createElement("li");
      line.textContent = "No augment slots were listed in this export; verify the item has no installed augments.";
      observationSlots.appendChild(line);
    }
    for (const child of item.children) {
      const line = document.createElement("li");
      line.textContent = `${child.location}: ${child.item_id ? `${child.name} (#${child.item_id})` : "Empty"}`;
      observationSlots.appendChild(line);
    }
  }
  itemSelect.addEventListener("change", updateObservation);
  review.addEventListener("input", () => { overwriteToken = ""; overwritePrompt.hidden = true; });
  document.getElementById("overwrite-accept").addEventListener("click", () => {
    overwritePrompt.hidden = true;
    review.requestSubmit();
  });
  document.getElementById("overwrite-decline").addEventListener("click", () => {
    overwriteToken = "";
    overwritePrompt.hidden = true;
    saveStats.checked = false;
    message("Existing stats will be kept. Save again to store the screenshot.");
  });

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
      const text = result.name_match_text.toLocaleLowerCase().replace(/\s+/g, " ");
      const matches = items.filter(item => containsItemName(text, item.name.toLocaleLowerCase().replace(/\s+/g, " ")));
      const suggestedIds = new Set(result.name_suggestions.map(item => item.id));
      const options = matches.length ? matches : items.filter(item => suggestedIds.has(item.id));
      const selected = options.length === 1 ? options[0] : null;
      itemSelect.value = selected ? String(selected.index) : "";
      updateObservation();
      suggestionButtons.replaceChildren();
      suggestions.hidden = options.length <= 1;
      for (const item of options.length > 1 ? options : []) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = `${item.name} (#${item.id}) · ${item.location} · row ${item.index}`;
        button.addEventListener("click", () => {
          itemSelect.value = String(item.index);
          updateObservation();
          matchHelp.textContent = "Possible match selected. Verify it against the screenshot.";
        });
        suggestionButtons.appendChild(button);
      }
      matchHelp.textContent = selected
        ? `Suggested from OCR: ${selected.name} (#${selected.id}). Verify before saving.`
        : "No unique OCR match. Select the correct item; possible matches are not verified.";
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
      if (overwriteToken) form.append("overwrite_token", overwriteToken);
      if (verifyObservation.checked) form.append("verify_observation", "yes");
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
      if (error.conflict) {
        overwriteToken = error.conflict.token;
        const action = error.conflict.decision === "confirm_merge"
          ? "Update conflicting values while preserving omitted fields"
          : "Replace the existing record";
        overwriteMessage.textContent = `${action}? Existing: ${error.conflict.old_count} populated stats; screenshot: ${error.conflict.new_count}.`;
        overwriteChanges.replaceChildren();
        for (const change of error.conflict.changes) {
          const item = document.createElement("li");
          item.textContent = `${change.field}: ${change.old == null ? "(missing)" : JSON.stringify(change.old)} → ${change.new == null ? "(missing)" : JSON.stringify(change.new)}`;
          overwriteChanges.appendChild(item);
        }
        overwritePrompt.hidden = false;
      }
    } finally {
      setBusy(false);
      if (!overwritePrompt.hidden) document.getElementById("overwrite-accept").focus();
    }
  });
})();
