"""Settings › Backups (wave L, form/backup.py): choose a folder, back up now, see the backup listed and verified, then
a deleted design in Recently deleted, put back with one press. Pictures: settings-backups-<dark|light>.png and
settings-backups-deleted-<dark|light>.png.

Everything happens in the journey's scratch folders (FORM_UITEST_TMP): the backup folder is made there."""
import os
from pathlib import Path

from _lib import make, open_sheet_wait


def run(ui):
    theme = "dark" if ui.js("Theme.dark") else "light"
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    pid = make(ui, "storage_box", "Backup box", open=False, purpose="model")
    folder = Path(os.environ["FORM_UITEST_TMP"]) / "backups"
    ui.api("/config", {"values": {"backup.folder": str(folder)}})
    ui.run_js("Store.loadConfig()")
    ui.run_js("Store.openSettings('backups')")
    open_sheet_wait(ui, "settings")
    ui.wait_until(lambda: ui.item("settingsTitle").property("text") == "Backups", 10, "the Backups page")
    ui.wait_until(lambda: ui.sees("No backup yet"), 15, "the status card")
    ui.click("backupNow")
    ui.wait_until(lambda: ui.sees("every file verified"), 120, "the backup to finish and verify")
    files = sorted(folder.glob("form-backup-*.zip"))
    ui.eq(len(files), 1, "one backup file in the folder")
    ui.wait_until(lambda: ui.sees(files[0].name), 10, "the backup listed")
    ui.settle(400)
    ui.shot(f"settings-backups-{theme}")
    # a deleted design is listed with its 30 days and the backup that holds it, and comes back with one press
    ui.api(f"/projects/{pid}/delete", {})
    ui.run_js("Store.openSettings('general')")
    ui.wait_until(lambda: ui.item("settingsTitle").property("text") == "General", 10, "another page")
    ui.click("settingsNav_backups")
    ui.wait_until(lambda: ui.sees("Backup box") and ui.sees("30 days left"), 15, "the deleted design in Recently deleted")
    ui.check(ui.sees("in " + files[0].name), "it says which backup holds it")
    ui.scroll_to(ui.item("backupDeleted"))
    ui.settle(400)
    ui.shot(f"settings-backups-deleted-{theme}")
    ui.click_text("Put back")
    ui.wait_until(lambda: any(p["id"] == pid for p in ui.api("/studio")["projects"]), 15, "the design to be back")
    ui.wait_until(lambda: ui.sees("Nothing deleted."), 15, "the bin to be empty")
    ui.key("Escape")
