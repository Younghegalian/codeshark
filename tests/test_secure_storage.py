import json
import tempfile
import unittest
from pathlib import Path

from codex_codeshark.automation import AgentStore
from codex_codeshark.learning import SkillStore
from codex_codeshark.memory import FeedbackStore, MemoryStore
from codex_codeshark.state import StateStore


class SecureStorageTests(unittest.TestCase):
    def _assert_temp_symlink_is_not_followed(self, kind: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()

            if kind == "state":
                target = runtime / "state.json"
                (runtime / "state.json.tmp").symlink_to(sentinel)
                StateStore(target).set_last_update_id(7)
                self.assertEqual(json.loads(target.read_text())["last_update_id"], 7)
            elif kind == "memory":
                target = runtime / "memory.json"
                (runtime / "memory.json.tmp").symlink_to(sentinel)
                MemoryStore(target).add("safe memory")
                self.assertEqual(json.loads(target.read_text())["memories"][0]["text"], "safe memory")
            else:
                skills = runtime / "skills"
                skills.mkdir()
                target = skills / "index.json"
                (skills / "index.json.tmp").symlink_to(sentinel)
                SkillStore(skills).add("Testing", "Run unittest")
                self.assertEqual(json.loads(target.read_text())["skills"][0]["id"], "s1")

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse(target.is_symlink())

    def test_state_temp_symlink_is_not_followed(self) -> None:
        self._assert_temp_symlink_is_not_followed("state")

    def test_memory_temp_symlink_is_not_followed(self) -> None:
        self._assert_temp_symlink_is_not_followed("memory")

    def test_skill_index_temp_symlink_is_not_followed(self) -> None:
        self._assert_temp_symlink_is_not_followed("skill")

    def test_feedback_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            store = FeedbackStore(runtime / "feedback.jsonl")
            sentinel = root / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            store.path.symlink_to(sentinel)
            with self.assertRaises(RuntimeError):
                store.record(
                    task_id="t1",
                    rating="good",
                    note="safe",
                    thread_id=None,
                    memory_ids=(),
                    skill_ids=(),
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_existing_runtime_permissions_are_hardened_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            runtime.mkdir(mode=0o755)
            database = runtime / "agent.db"
            AgentStore(database)
            runtime.chmod(0o755)
            database.chmod(0o644)

            AgentStore(database)
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
            self.assertEqual(database.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
