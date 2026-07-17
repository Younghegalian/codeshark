import tempfile
import unittest
from pathlib import Path

from codex_codeshark.memory import MemoryStore
from codex_codeshark.personal_sync import PersonalDataSync, PersonalSyncError, PersonalSyncStatus


class PersonalDataSyncTests(unittest.TestCase):
    def test_pushes_and_restores_a_private_personal_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            remote = root / "remote"
            target = root / "target"
            remote.mkdir()
            MemoryStore(source / "memory.json").add("Use concise replies")

            source_sync = PersonalDataSync(source)
            source_sync.configure(remote)
            pushed = source_sync.push()
            self.assertTrue(pushed.archive.is_file())
            self.assertTrue(source_sync.status().automatic)

            target_sync = PersonalDataSync(target)
            target_sync.configure(remote)
            pulled = target_sync.pull(replace=True)
            self.assertEqual(pulled.files, pushed.files)
            self.assertEqual(MemoryStore(target / "memory.json").list()[0].text, "Use concise replies")

    def test_sync_requires_a_local_existing_absolute_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sync = PersonalDataSync(Path(directory) / "runtime")
            with self.assertRaisesRegex(PersonalSyncError, "absolute"):
                sync.configure(Path("relative"))

    def test_disable_returns_to_a_clean_disabled_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            shared = root / "shared"
            shared.mkdir()
            sync = PersonalDataSync(runtime)

            sync.configure(shared)
            sync.disable()

            self.assertEqual(sync.status(), PersonalSyncStatus(None, False))
