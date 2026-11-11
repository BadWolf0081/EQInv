"use strict";

document.querySelectorAll(".icon-selector").forEach(selector => {
  const container = selector.querySelector(".icon-source");
  const image = container.querySelector("img");
  const outline = selector.querySelector(".icon-selection");
  const fields = ["icon-x", "icon-y", "icon-width", "icon-height"].map(
    name => selector.querySelector(`.${name}`)
  );
  const canvas = selector.querySelector(".icon-preview");
  let start = null;

  function redraw() {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const values = fields.map(field => Number(field.value));
    const [x, y, width, height] = values;
    const valid = fields.every(field => field.value !== "") && values.every(Number.isSafeInteger) &&
      x >= 0 && y >= 0 && width > 0 && height > 0 && width <= 512 && height <= 512 &&
      x + width <= image.naturalWidth && y + height <= image.naturalHeight;
    outline.hidden = !valid;
    if (!valid) return;
    outline.style.left = `${100 * x / image.naturalWidth}%`;
    outline.style.top = `${100 * y / image.naturalHeight}%`;
    outline.style.width = `${100 * width / image.naturalWidth}%`;
    outline.style.height = `${100 * height / image.naturalHeight}%`;
    ctx.drawImage(image, x, y, width, height, 0, 0, canvas.width, canvas.height);
  }

  function point(event) {
    const rect = image.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(image.naturalWidth, Math.round((event.clientX - rect.left) * image.naturalWidth / rect.width))),
      y: Math.max(0, Math.min(image.naturalHeight, Math.round((event.clientY - rect.top) * image.naturalHeight / rect.height)))
    };
  }

  function update(event) {
    const end = point(event);
    const values = [Math.min(start.x, end.x), Math.min(start.y, end.y),
      Math.abs(start.x - end.x), Math.abs(start.y - end.y)];
    fields.forEach((field, index) => { field.value = values[index]; });
    redraw();
  }

  container.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !image.naturalWidth || fields[0].disabled) return;
    event.preventDefault();
    start = point(event);
    container.setPointerCapture(event.pointerId);
    update(event);
  });
  container.addEventListener("pointermove", event => { if (start) update(event); });
  container.addEventListener("pointerup", event => { if (start) { update(event); start = null; } });
  container.addEventListener("pointercancel", () => { start = null; });
  fields.forEach(field => field.addEventListener("input", redraw));
  image.addEventListener("load", redraw);
  function clear() {
    fields.forEach(field => { field.value = ""; });
    redraw();
  }
  selector.addEventListener("clear-icon", clear);
  selector.querySelector(".clear-icon").addEventListener("click", clear);
});
