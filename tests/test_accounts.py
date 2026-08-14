from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.accounts import AccountRegistry


class AccountRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name) / "data"

    def test_registry_exposes_legacy_paths_without_moving_data(self):
        self.data_dir.mkdir()
        books_path = self.data_dir / "books.json"
        books_path.write_text("[]", encoding="utf-8")

        registry = AccountRegistry(self.data_dir)
        account = registry.active()

        self.assertEqual(account.profile_id, "legacy")
        self.assertEqual(account.display_name, "默认账号")
        self.assertEqual(registry.workspace_dir(account.profile_id), self.data_dir)
        self.assertEqual(
            registry.edge_profile_dir(account.profile_id),
            self.data_dir / "fanqie-edge-profile",
        )
        self.assertTrue(books_path.exists())

    def test_new_profile_has_isolated_workspace_and_edge_profile(self):
        registry = AccountRegistry(self.data_dir)

        first = registry.add("作家 B")
        account = registry.add("作家 C")

        self.assertEqual(
            registry.workspace_dir(account.profile_id),
            self.data_dir / "accounts" / account.profile_id / "workspace",
        )
        self.assertEqual(
            registry.edge_profile_dir(account.profile_id),
            self.data_dir / "accounts" / account.profile_id / "edge-profile",
        )
        self.assertEqual(registry.active().profile_id, account.profile_id)
        self.assertNotEqual(first.debug_port, account.debug_port)
        self.assertGreater(first.debug_port, 9222)

    def test_selected_profile_and_guide_state_survive_reopen(self):
        registry = AccountRegistry(self.data_dir)
        account = registry.add("作家 B")
        registry.rename(account.profile_id, "作家 B 新号")
        registry.mark_guide_seen(account.profile_id)

        restored = AccountRegistry(self.data_dir)

        self.assertEqual(restored.active().display_name, "作家 B 新号")
        self.assertTrue(restored.active().guide_seen)

    def test_blank_or_unknown_profile_operations_are_rejected(self):
        registry = AccountRegistry(self.data_dir)

        with self.assertRaisesRegex(ValueError, "账号名称"):
            registry.add("  ")
        with self.assertRaisesRegex(KeyError, "未知账号"):
            registry.set_active("unknown")


if __name__ == "__main__":
    unittest.main()
