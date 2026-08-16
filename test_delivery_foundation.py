"""Tests for desktop delivery paths and safe legacy database migration."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.database import create_periodic_backup, migrate_legacy_database, resolve_database_path


class DeliveryFoundationTests(unittest.TestCase):
    def test_data_directory_takes_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / "qagent_pet.db"
            self.assertEqual(resolve_database_path(directory, "sqlite:///ignored.db"), str(expected))

    def test_sqlite_url_is_supported(self):
        self.assertEqual(
            resolve_database_path("", "sqlite+aiosqlite:///./custom.db"),
            "custom.db",
        )

    def test_legacy_database_is_backed_up_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "legacy.db"
            target = root / "app-data" / "qagent_pet.db"

            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE memories (content TEXT NOT NULL)")
                db.execute("INSERT INTO memories(content) VALUES (?)", ("kept",))
                db.commit()

            self.assertTrue(migrate_legacy_database(str(target), str(source)))
            with sqlite3.connect(target) as db:
                row = db.execute("SELECT content FROM memories").fetchone()
            self.assertEqual(row[0], "kept")
            self.assertFalse(migrate_legacy_database(str(target), str(source)))

    def test_periodic_backup_is_created_only_once_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "qagent_pet.db"
            backup_dir = root / "backups"
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE state (value TEXT NOT NULL)")
                db.execute("INSERT INTO state(value) VALUES ('safe')")
                db.commit()

            backup = create_periodic_backup(str(source), str(backup_dir), keep=5)
            self.assertTrue(Path(backup).is_file())
            self.assertEqual(create_periodic_backup(str(source), str(backup_dir), keep=5), "")
            with sqlite3.connect(backup) as db:
                value = db.execute("SELECT value FROM state").fetchone()[0]
            self.assertEqual(value, "safe")


if __name__ == "__main__":
    unittest.main()
