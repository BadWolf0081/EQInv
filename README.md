# The Adventurer's Ledger

A local, unofficial EverQuest inventory viewer. Upload `/outputfile inventory` text files to store the complete original export and its parsed rows in MariaDB, then browse equipped gear, its augments, inventory, bank, and keyring. Discord login restricts access to members with a configured server role. Each Discord user has up to ten private character profiles. Item data, screenshots and icons are shared across authorized users. Older uploads are retained, but a history browser and live game integration are not implemented.

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
cp config.example.ini config.ini
chmod 600 config.ini
```

Edit `config.ini` in the project directory and enter the MariaDB connection details, including the password chosen above. It is read automatically for the website and Flask commands, regardless of the current working directory. It contains secrets: restrict access to the application account, keep it out of backups or shares that aren't suitably protected, and never commit or publish it. The provided `.gitignore` excludes `config.ini`.

### Configure Discord login

1. In the Discord Developer Portal create an application and bot, and copy the application ID, client secret, and bot token. Keep the two secrets private. Under OAuth2, add the exact callback URL, for example `https://inventory.example.com/auth/discord/callback`. For local testing only, `http://127.0.0.1:5000/auth/discord/callback` is allowed.
2. Invite the bot to the required Discord server using the application's OAuth2 URL Generator with the **bot** scope. It must remain in the server so it can look up members. Copy the server ID and the required role ID (Discord Developer Mode exposes **Copy ID**). The user must have that exact role; server membership alone is not enough.
3. Fill in the Discord settings in `config.ini`. Use numeric Discord IDs and the same redirect URL registered above. Generate a long random session secret, for example with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`, and enter it as `EQINV_SECRET_KEY`. It must be at least 32 characters and remain the same across restarts. Do not copy example IDs or secrets from elsewhere.

Existing environment-variable configurations continue to work: an environment variable overrides the matching INI setting, even if it is empty. The INI file is optional if all settings are supplied through the environment. Restart the application after editing `config.ini`; malformed files or unrecognized settings produce a startup error. Values are literal, so passwords containing `%` work without escaping. Configuration names are case-sensitive.

The application requests Discord's `identify` scope and checks the user's server membership and role with the bot at login and at least every 30 seconds during active use. This short cache avoids a Discord request for every item icon; role removal can take up to 30 seconds to take effect. A missing role or removed membership denies access; when a check is due, a Discord outage or rate limit also fails closed. Login sessions expire after 12 hours of inactivity. The bot token is not used to upload inventories or post messages. Rotating the session secret invalidates existing sessions.

Initialize the database and start the application:

```bash
python -m flask --app app init-db
python app.py
```

For local testing with the localhost callback, open `http://127.0.0.1:5000` on the same computer. The virtual environment activation and any environment overrides apply only to the current shell; set them again before restarting.

For temporary testing from a different computer on a trusted LAN, an administrator can opt in to an HTTP callback using the **server's** private IPv4 address, for example:

```ini
EQINV_DISCORD_REDIRECT_URI = http://10.10.11.3:5000/auth/discord/callback
EQINV_ALLOW_INSECURE_LAN_HTTP = true
```

Replace `10.10.11.3` with the actual address of the server running the application, not the browser computer's address. Register the exact same callback in the Discord Developer Portal, restart the application, and open `http://10.10.11.3:5000` (using your server's address) in the other computer's browser. Firewall rules must permit access to port 5000. The override accepts only private IPv4 addresses in `10/8`, `172.16/12`, or `192.168/16`, not public IPs or hostnames. Discord must accept the callback too; this app setting cannot override Discord's restrictions.

**HTTP is unencrypted:** people on the network may be able to steal login codes or session cookies and read or change private inventories. Use this option only on a trusted network, never expose it to the internet, and set it back to `false` when switching to HTTPS.

If the Linux host is remote, connect from your own computer using SSH port forwarding: `ssh -L 5000:127.0.0.1:5000 user@linux-host`. Leave that connection open and visit `http://127.0.0.1:5000` on your computer. Replace `user@linux-host` with your SSH destination. The inventory file can remain on the computer running the browser; select it in the upload form.

The development server binds to **all IPv4 interfaces** (`0.0.0.0`) and does not provide HTTPS. Restrict its port with host and network firewall rules. Flask's development server is not intended for production. For remote use, run a production WSGI server behind HTTPS and keep the backend port inaccessible externally; the public HTTPS callback must exactly match the registered URL. The application stores original inventory contents and filenames in MariaDB. The default 10 MB upload limit applies to both forms.

### Existing installations and legacy uploads

Back up the database, then rerun `python -m flask --app app init-db` before using this version. Existing uploads are not assigned automatically. With the app stopped, an administrator can assign **all unowned uploads** to one Discord account by running:

```bash
python -m flask --app app claim-legacy DISCORD_USER_ID
```

Replace `DISCORD_USER_ID` with the intended user's numeric Discord ID, not their username, server ID or role ID. The claim groups matching character/server filenames and selects the latest upload for each profile; all claimed uploads stay owned by that account. It refuses to claim anything if an upload lacks a character or server, the claim conflicts with an existing profile, or the result would exceed ten profiles. Resolve those cases with a database backup and a deliberate administrator-assisted data migration before retrying; do not assign unknown inventories to a user without verifying ownership. The claim does not change item catalog data or images.

Transactions and the ten-profile limit rely on InnoDB. New installations create these tables with InnoDB; on an upgraded database verify that `uploads` and `items` also use InnoDB, and migrate any non-InnoDB tables using an appropriate backup and MariaDB administration procedure before claiming or uploading.

## Import inventory

In EverQuest, use `/outputfile inventory`. Select the resulting `Character_Server-Inventory.txt` on the website; both character and server are required in the filename. Profile identity is the character name and server, compared case-insensitively. Uploading the same character and server replaces the profile's displayed snapshot; the previous upload remains stored. Different servers count as different profiles. Choose among your profiles using the selector; other Discord users cannot browse your character uploads. The keyring's additional fields are retained in the original and parsed data.

Click an item or augment name in the gear, comparison, or inventory lists to see its imported stats and augment types. The detail page also shows the direct child slots from that specific exported item, including their imported stats; container contents are listed the same way. Follow a child link to see its own details. Empty slots are not items. Missing catalog values are marked unknown or not imported, and the export's `Slots` value is not an augment type.

The inventory window displays equipped slots and General 1–10 in a game-inspired arrangement. Repeated slots follow their order in the export; labels distinguish the two ears, wrists, and fingers. Slots not present in the export are marked as such, rather than assumed empty. Other locations and bag contents remain available in the full inventory list. Saved icon crops appear in their slots; otherwise a labeled placeholder is shown. Select an occupied slot to open its saved item screenshot, when available, with a link to item details and augments. Without a saved screenshot (or with JavaScript unavailable), the slot opens the item details directly. The character's appearance and current stats are not in the export and are not recreated.

Hover over or keyboard-focus an equipped item to preview its installed augments. Known socket types guide the display: type 3 shows skill modifiers, type 5 the largest known positive heroic stat, types 13 and 14 purity, type 21 "Ornament", and type 22 ornamentation; other types show HP and mana or the largest heroic stat. If the socket type is unknown, a recorded skill modifier is shown without assuming the socket type; an augment compatible exclusively with types 13 and/or 14 instead shows purity, and one compatible only with type 21 shows "Ornament". Unknown values remain unknown. An installed type 22 ornament warns that an item's icon can show its ornamented appearance. Stored items with known numbered sockets also get previews; container contents are not assumed to be augments.

Choose **Browse and compare augments** to list equipped augments, augments in known sockets of stored items, and loose items with recorded compatible augment types. Loose augments without known types cannot be identified from the export. The known non-augment Perfected Augmentation Distiller (item ID 52023) is excluded even if incorrect augment data was saved to it; the list warns about that data without deleting it. Other items with incorrect compatible-type data may still appear because the export does not identify their item type. Each inventory row remains separate, including duplicates. Search names, locations, IDs or recorded stats; filter by location or compatible/installed type; and sort by numeric stat or name in either direction. A minimum applies to the selected numeric stat and excludes unknown values. Missing and nonnumeric values sort last, not as zero. Compatible types and installed socket types are shown separately; matching a type does not establish full compatibility. Stats are shared catalog values, not historical snapshots.

To calculate stats before augments, import a new screenshot of an equipped item and explicitly confirm that every listed inventory slot and the reviewed screenshot values match by checking the observation option in the screenshot importer. This creates a separate observation tied to that upload, item row, screenshot and augment list. Saving the observation does not itself overwrite shared item data, although the separate catalog-save option can update it. On the item detail page, select **Without augment stats** to switch from shared catalog values to that verified screenshot's additive totals minus its augments; the two sources need not be the same. The subtraction uses current shared augment catalog values and is calculated only where **every** confirmed augment has an explicit numeric contribution, including explicit zero. Missing values are unknown, not zero. Unknown socket types and installed type 13 or 14 purity augments block subtraction; power-source and other effects are not calculated and may still affect the result. Existing screenshots have no verified augment snapshot and must be reviewed again. Run `python -m flask --app app init-db` after upgrading to create the observation table.

When no manually selected icon exists, the site attempts to derive one from the latest saved item-window screenshot. It looks for the item window's title and blue tab frame, removes the blue window texture around the artwork, and centers it on a transparent background. The icon is generated from the saved screenshot, not written to the icon table; this also applies to previously saved screenshots. Different game UI skins, scales, or loosely cropped windows may not be recognized or may need correction. Artwork close in color to the background may be lost. If the icon is missing or incorrect, open the item details and use **Select or replace icon from saved screenshot**; a manually saved icon always takes precedence and is not modified.

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

In the game on Windows 11, open one or more item inspection windows and take a screenshot using your normal Windows screenshot tool. Keep each window and its name, stats, and augmentation type legible. On the website, choose **Import item screenshots** from the inventory or an item page. Select a PNG or JPEG, then drag a rectangle around one complete item window (or enter its pixel coordinates) and choose **Recognize selected window**. Review the crop, item match, and values, then save; repeat for each other item in the same screenshot. A unique exact-name match is preselected. If no exact match is found, a single similar OCR suggestion is preselected; multiple matching inventory rows require a choice, including repeated copies of the same item. Recognized augment removal instructions are excluded from name matching, but retained in the OCR text. Verify the item against the image; neither exact nor approximate matches verify item identity. Window boundaries are selected manually, not detected automatically. No companion needs to run alongside the game.

OCR runs locally on the Linux server and suggests some visible stats and augment types. It recognizes common inspection-window labels such as purity, mana regeneration, heal amount, spell damage, clairvoyance, tribute, required level, size and skill modifiers; other fields may need to be added manually. The observed OCR misreading `Purily` is also recognized as purity, but other misreadings still require manual correction. A recognized classed augmentation distiller is suggested as `distiller_class`, using Roman numerals `I` through `XXX`; an explicitly recognized perfected-only requirement is `"Perfected only"`. A perfected distiller mentioned as an alternative to a classed distiller does not mean perfected-only. The OCR readings `XIL` and `XILL` are suggested as `XII` and `XIII` respectively; verify these corrections against the screenshot. Other invalid readings are kept for review but cannot be saved until corrected to a valid class or removed. Verify the full removal instructions, including alternatives, in the screenshot or recognized text. Compare the screenshot and the recognized text carefully, correct the suggested JSON and types, add missing stats yourself, then confirm and save. Use `7|8` for a type 7/8 augment; an item's socket numbers are not augment types. `ac`, `hp`, `mana`, and `endurance` must be whole numbers; additional stats may be numbers or strings. Empty or unrecognized values are not assumed to be zero. After saving, the reviewed values join the existing catalog and can appear in the augment comparison. Corrected OCR text is saved with the stats. Only selected crops are sent to the server; the full screenshot stays in your browser. Each confirmed crop is stored in MariaDB, with the most recent shown on the item detail page. Stored crops are shared with all authorized users, may reveal character-specific information, and are not private; exclude sensitive information. No data is sent to a third-party OCR service.

For the seven attributes, OCR accepts full names and abbreviations. A visible value such as `Strength: 64 +89` is suggested as numeric `str: 64` and `heroic_str: 89`; the other attribute keys are `sta`, `agi`, `dex`, `wis`, `int`, and `cha`, with corresponding `heroic_` keys. Magic, fire, cold, disease, poison and corruption resistances, attack, HP/mana/endurance regeneration, heal amount, spell damage and clairvoyance are also recognized. If a resistance has a visible heroic component, it is stored separately in a `heroic_` field. Missing heroic values are unknown, not zero. Weight is stored as text to preserve decimals. These fields are kept in the existing `item_data.stats_json`, so no database migration is needed. Older saved records are not automatically reprocessed and may still contain combined strings such as `"+22+16"`.

Screenshot catalog saves compare populated stat fields with the current record. More populated stats replace the entire record automatically, including its compatible augment types and any fields omitted from the new review. Equal counts require confirmation before replacing the entire record. Fewer stats preserve omitted or blank fields and existing augment types when no new types are provided; conflicting values require confirmation before merging. Zero is populated. The count excludes OCR text, socket types, compatible types, item flags, equipment slots, size, weight, distiller class, source, level requirements and tribute; other nonblank fields, including skill modifiers, count. The confirmation shows changed fields and is checked again against the current data when saved. Decline the update or uncheck the stats option to save only the crop. Item data is shared by item ID across uploads, and screenshot values can include installed augments; changing it affects every upload that uses that ID. Previously verified observations and screenshots are retained separately. All confirmed crops are retained, even though only the latest is displayed. Upgrading installations must run `python -m flask --app app init-db` to create the screenshot table before using this feature. OCR is imperfect and this workflow has not been calibrated against every EverQuest item window; verify the correct item and every value. The upload limit is 10 MB and screenshots must be no larger than 20 megapixels. This workflow does not inspect game memory, capture network traffic, or interact with the game process.

To add an item icon while reviewing a screenshot, drag around the icon near the upper-left of the item window and check the icon preview before confirming. The selection is manual because window sizes and positions vary; no icon is saved unless selected. The crop is saved by item ID in MariaDB, appears next to that item in equipment, augment and inventory lists, and replaces the previous icon for the same ID. To add or replace an icon from an already saved screenshot, open the item detail page and choose **Select or replace icon from saved screenshot**; this does not change item stats. Icons are shared with all authorized users and can be replaced by them. On an existing installation, run `python -m flask --app app init-db` before starting the updated app to create the icon table.

## Import item data

Upload a UTF-8 CSV using the item data form. `id` and `aug_types` headers are required; type numbers are separated by `|`. `ac`, `hp`, `mana`, and `endurance` must be whole numbers when provided. Any other columns are preserved and displayed as text for matching items. Blank values mean unknown. Example (illustrative values, not real item data):

`aug_types` contains the slot types an augmentation **fits into**, not the types of sockets on an item. Screenshot review suggests these from the “This Augmentation fits in slot types” text; verify all suggested values. Confirmed types are stored in `item_data.aug_types_json` by item ID and shown on item details. Screenshot updates follow the comparison rules above.

For an item that holds augments, its own numbered socket types are separate fields in `item_data.stats_json`: `socket_1_type`, `socket_2_type`, and so on. OCR suggests these from lines such as `Slot 1, type 3`; verify the slot numbers and types, and add or correct them in the review JSON. CSV imports can use the same column names; values must be integers from 1 to 255 or blank. Item details show known socket types and compare them with the compatible types of direct child augments from the inventory. An exact number match is shown as such; a nonmatch is not a definitive compatibility judgment and should be checked in game. Missing information is unknown.

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
