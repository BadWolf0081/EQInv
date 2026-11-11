# The Adventurer's Ledger

A local, unofficial EverQuest inventory viewer. Upload `/outputfile inventory` text files to store the complete original export and its parsed rows in MariaDB, then browse equipped gear, its augments, inventory, bank, and keyring. Every upload is retained; the site shows the latest upload. Accounts, browsing history, Discord, and live game integration are not implemented.

## What the export can and cannot tell us

The export contains names, IDs, locations, counts, and slots—not item stats, augment types, or current character stats. Gear and augments are associated by their order and location in the export, including repeated ears, wrists, and fingers. The `Slots` column is **not** an augment type.

The type 7/8 comparison uses the separate manually imported item catalog below. It sorts known AC values lowest first, places unknown AC last, and reports equipped augments with unknown types separately. Catalog values are not character totals. The character screenshot is not imported or used to infer stats. Item metadata is shared by ID and reflects the latest catalog import, not a historical snapshot of stats.

## Linux setup

Requires Python 3.10+ with `venv`, pip, and a running MariaDB server. For example, on Debian or Ubuntu:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip mariadb-server
sudo systemctl enable --now mariadb
```

Other Linux distributions use different package and service names. Check `python3 --version` if your distribution ships multiple Python versions.

Open the MariaDB administrator shell with `sudo mariadb`, then create a database and a dedicated user. Choose a strong password, substitute it below, and keep it private:

```sql
CREATE DATABASE eqinv CHARACTER SET utf8mb4;
CREATE USER 'eqinv'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT ALL PRIVILEGES ON eqinv.* TO 'eqinv'@'localhost';
EXIT;
```

From the project directory on the Linux host:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export EQINV_DB_HOST=127.0.0.1
export EQINV_DB_PORT=3306
export EQINV_DB_NAME=eqinv
export EQINV_DB_USER=eqinv
```

Enter the MariaDB password you chose when creating the database user. The password will not appear as you type:

```bash
read -rs -p "MariaDB password: " EQINV_DB_PASSWORD
echo
export EQINV_DB_PASSWORD
```

`read` prompts for the password and stores it in the variable, `echo` moves to a new line, and `export` makes the variable available to the application. Then initialize the database and start the application:

```bash
python -m flask --app app init-db
python app.py
```

Open `http://127.0.0.1:5000` in a browser on the Linux host, or `http://<linux-host-ip>:5000` from another computer on your trusted network. Use the host's actual IP address, not `0.0.0.0`. Network and firewall rules must permit access to port 5000. The environment variables and virtual environment activation apply only to the current shell; set them again before restarting. Optionally set `EQINV_SECRET_KEY` to a persistent, long random secret to keep flash messages valid across restarts. Keep secrets out of the repository and shell history.

If the Linux host is remote, connect from your own computer using SSH port forwarding: `ssh -L 5000:127.0.0.1:5000 user@linux-host`. Leave that connection open and visit `http://127.0.0.1:5000` on your computer. Replace `user@linux-host` with your SSH destination. The inventory file can remain on the computer running the browser; select it in the upload form.

The development server binds to **all IPv4 interfaces** (`0.0.0.0`) and has **no authentication or HTTPS**: anyone who can reach port 5000 can view the inventory and upload or replace item data. Restrict access to trusted devices using host and network firewall rules; do not expose it to the internet or an untrusted network. Flask's development server is not intended for production. The application saves uploaded inventory contents and filenames in the configured database. The default 10 MB upload limit applies to both forms.

## Import inventory

In EverQuest, use `/outputfile inventory`. Select the resulting `Character_Server-Inventory.txt` on the website. The name and server are inferred from the filename if it follows that pattern; otherwise they are shown as unknown. Re-export and upload again to refresh the snapshot. The keyring's additional fields are retained in the original and parsed data.

Click an item or augment name in the gear, comparison, or inventory lists to see its imported stats and augment types. The detail page also shows the direct child slots from that specific exported item, including their imported stats; container contents are listed the same way. Follow a child link to see its own details. Empty slots are not items. Missing catalog values are marked unknown or not imported, and the export's `Slots` value is not an augment type.

Every successful upload also adds each previously unseen nonzero item ID and its first observed name to the `items` table, including equipped gear, augments, bags, bank, and keyring items. Duplicate IDs and empty slots are not added. The inventory and item catalog are saved in the same transaction. Existing names are not overwritten on later uploads. The manually imported `item_data` table remains separate and can be joined using `item_id`; uploads never overwrite its stats or augment types.

If upgrading an existing installation, activate the virtual environment and set the database environment variables above, then run `python -m flask --app app init-db` again before starting the app. It creates the `items` table and backfills it from all previously saved uploads, in upload order. Running it again is safe and does not replace existing entries.

## Import Lucy item references

Lucy offers an [item ID/name list](https://lucy.allakhazam.com/downloads.html). Download `itemlist.txt.gz` from that page to the Linux host and, with the virtual environment active and database variables set, run:

```bash
python -m flask --app app init-db
python -m flask --app app import-lucy itemlist.txt.gz
```

An uncompressed `itemlist.txt` works too. Importing is transactional and can be repeated; it adds or updates IDs in a separate `lucy_items` reference table without altering your seen items or manually imported stats. IDs omitted from a subsequent list remain. The `init-db` command creates the reference table on existing installations.

Item detail pages show a link to Lucy when that item ID appears in the imported list. The link opens Lucy in your browser; the app does not fetch or scrape the page or its images. The list contains only IDs, names, and links—not item images, stats, or augment types—so it cannot populate comparisons by itself. Use the screenshot or manual item data import below for those values. Check the source's terms and obtain permission before redistributing its data.

Lucy links are constructed from the item ID rather than stored as full URLs. Each item detail page also provides an Allakhazam name-search link, even when the item is absent from the Lucy list. Allakhazam uses different page IDs and names can be duplicated, so check the item ID in the search results before selecting an entry. Neither link imports stats automatically.

## Import stats from an item screenshot

Install Tesseract OCR with English language data on the **Linux server**. On Debian or Ubuntu:

```bash
sudo apt install tesseract-ocr tesseract-ocr-eng
python -m pip install -r requirements.txt
```

In the game on Windows 11, open one or more item inspection windows and take a screenshot using your normal Windows screenshot tool. Keep each window and its name, stats, and augmentation type legible. On the website, choose **Import item screenshots** from the inventory or an item page. Select a PNG or JPEG, then drag a rectangle around one complete item window (or enter its pixel coordinates) and choose **Recognize selected window**. Review the crop, item match, and values, then save; repeat for each other item in the same screenshot. The app suggests an inventory item only when its exact name appears in the OCR and the match is unique. Check the suggested item carefully; choose an item manually if there is no unique match. Window boundaries are selected manually, not detected automatically. No companion needs to run alongside the game.

OCR runs locally on the Linux server and suggests some visible stats and augment types. It recognizes common inspection-window labels such as mana regeneration, heal amount, spell damage, clairvoyance, tribute, required level, size and skill modifiers; other fields may need to be added manually. When a classed augmentation distiller is recognized, its Roman numeral is suggested as `distiller_class` (for example, `"distiller_class": "XXI"`); verify the full removal instructions, including any alternatives, in the screenshot or recognized text. Compare the screenshot and the recognized text carefully, correct the suggested JSON and types, add missing stats yourself, then confirm and save. Use `7|8` for a type 7/8 augment; an item's socket numbers are not augment types. `ac`, `hp`, `mana`, and `endurance` must be whole numbers; additional stats may be numbers or strings. Empty or unrecognized values are not assumed to be zero. After saving, the reviewed values join the existing catalog and can appear in the augment comparison. Corrected OCR text is saved with the stats. Only selected crops are sent to the server; the full screenshot stays in your browser. Each confirmed crop is stored in MariaDB, with the most recent shown on the item detail page. Stored crops are available to anyone who can reach the site; exclude private information. No data is sent to a third-party OCR service.

Screenshot imports refuse to overwrite any existing item catalog record, including one imported while you are reviewing. To save only a crop for an item with existing data, uncheck the stats option; use the CSV import below if you intentionally need to replace a record. All confirmed crops are retained, even though only the latest is displayed. Upgrading installations must run `python -m flask --app app init-db` to create the screenshot table before using this feature. OCR is imperfect and this workflow has not been calibrated against every EverQuest item window; verify the correct item and every value. The upload limit is 10 MB and screenshots must be no larger than 20 megapixels. This workflow does not inspect game memory, capture network traffic, or interact with the game process.

## Import item data

Upload a UTF-8 CSV using the item data form. `id` and `aug_types` headers are required; type numbers are separated by `|`. `ac`, `hp`, `mana`, and `endurance` must be whole numbers when provided. Any other columns are preserved and displayed as text for matching items. Blank values mean unknown. Example (illustrative values, not real item data):

`aug_types` contains the slot types an augmentation **fits into**, not the types of sockets on an item. Screenshot review suggests these from the “This Augmentation fits in slot types” text; verify all suggested values. Confirmed types are stored in `item_data.aug_types_json` by item ID and shown on item details. Existing catalog records are not updated by screenshot imports.

```csv
id,aug_types,ac,hp,mana,source
12345,7|8,42,120,100,manual
12346,7,,150,,manual
```

Each import replaces the complete catalog record for each included ID; other IDs are unchanged. Include all fields you want to keep for those IDs. A blank `aug_types` means unknown. No item data is automatically downloaded, and an item omitted from this catalog cannot be ranked. Verify the source and accuracy of your manually entered data.

## Tests

```bash
python -m unittest discover -s tests -v
```
