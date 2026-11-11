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
read -rs -p "MariaDB password: " EQINV_DB_PASSWORD; echo
export EQINV_DB_PASSWORD
python -m flask --app app init-db
python app.py
```

Open `http://127.0.0.1:5000` in a browser on the Linux host. The environment variables and virtual environment activation apply only to the current shell; set them again before restarting. Optionally set `EQINV_SECRET_KEY` to a persistent, long random secret to keep flash messages valid across restarts. Keep secrets out of the repository and shell history.

If the Linux host is remote, connect from your own computer using SSH port forwarding: `ssh -L 5000:127.0.0.1:5000 user@linux-host`. Leave that connection open and visit `http://127.0.0.1:5000` on your computer. Replace `user@linux-host` with your SSH destination. The inventory file can remain on the computer running the browser; select it in the upload form.

The development server binds to localhost and has **no authentication**. Do not expose it to the internet or an untrusted network. It saves uploaded inventory contents and filenames in the configured database. The default 10 MB upload limit applies to both forms.

## Import inventory

In EverQuest, use `/outputfile inventory`. Select the resulting `Character_Server-Inventory.txt` on the website. The name and server are inferred from the filename if it follows that pattern; otherwise they are shown as unknown. Re-export and upload again to refresh the snapshot. The keyring's additional fields are retained in the original and parsed data.

Every successful upload also adds each previously unseen nonzero item ID and its first observed name to the `items` table, including equipped gear, augments, bags, bank, and keyring items. Duplicate IDs and empty slots are not added. The inventory and item catalog are saved in the same transaction. Existing names are not overwritten on later uploads. The manually imported `item_data` table remains separate and can be joined using `item_id`; uploads never overwrite its stats or augment types.

If upgrading an existing installation, activate the virtual environment and set the database environment variables above, then run `python -m flask --app app init-db` again before starting the app. It creates the `items` table and backfills it from all previously saved uploads, in upload order. Running it again is safe and does not replace existing entries.

## Import item data

Upload a UTF-8 CSV using the item data form. `id` and `aug_types` headers are required; type numbers are separated by `|`. `ac`, `hp`, `mana`, and `endurance` must be whole numbers when provided. Any other columns are preserved and displayed as text for matching items. Blank values mean unknown. Example (illustrative values, not real item data):

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
