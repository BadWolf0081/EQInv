const search = document.querySelector("#inventory-search");
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
