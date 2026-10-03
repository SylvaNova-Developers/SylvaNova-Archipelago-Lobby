import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

ap_path = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, ap_path)

import apworld_peers  # noqa: E402


class DiscoverPeerWorldImportsTests(unittest.TestCase):
    def test_tww3_imports_oot(self):
        apworld_path = os.environ.get("TWW3_APWORLD_PATH", "/tmp/tww3.apworld")
        if not os.path.isfile(apworld_path):
            self.skipTest(f"tww3 apworld not available at {apworld_path}")

        peers = apworld_peers.discover_peer_world_imports(apworld_path, "tww3")
        self.assertIn("oot", peers)
        self.assertNotIn("tww3", peers)
        self.assertNotIn("generic", peers)

    def test_minimal_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "child.apworld")
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "child/__init__.py",
                    "from worlds.oot import location_name_to_id\n",
                )
                zf.writestr(
                    "child/world.py",
                    "from worlds.generic.Rules import forbid_item\n",
                )

            peers = apworld_peers.discover_peer_world_imports(path, "child")
            self.assertEqual(peers, {"oot"})


class FindBundledApworldTests(unittest.TestCase):
    def test_prefers_custom_dir_and_parses_version(self):
        with tempfile.TemporaryDirectory() as supported, tempfile.TemporaryDirectory() as custom:
            open(os.path.join(supported, "oot-0.5.1.apworld"), "wb").close()
            open(os.path.join(custom, "oot-9.9.9.apworld"), "wb").close()

            # Import handler only when Archipelago deps are available.
            try:
                import handler  # noqa: E402
            except ModuleNotFoundError as exc:
                self.skipTest(f"handler dependencies unavailable: {exc}")

            ap_handler = handler.ApHandler(supported, custom)
            path, version = ap_handler._find_bundled_apworld("oot")
            self.assertEqual(version, "9.9.9")
            self.assertTrue(path.endswith("oot-9.9.9.apworld"))


class WorldSourceLoadFalseTests(unittest.TestCase):
    def test_load_world_from_zip_retries_when_world_source_returns_false(self):
        try:
            import handler  # noqa: E402
        except ModuleNotFoundError as exc:
            self.skipTest(f"handler dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as supported, tempfile.TemporaryDirectory() as custom:
            child_path = os.path.join(custom, "child-1.0.0.apworld")
            with zipfile.ZipFile(child_path, "w") as zf:
                zf.writestr("child/__init__.py", "from worlds.oot import location_name_to_id\n")
                zf.writestr("child/archipelago.json", '{"game": "Child Game"}')

            open(os.path.join(supported, "oot-0.6.7.apworld"), "wb").close()
            dest = os.path.join(custom, "child.apworld")
            shutil.copy(child_path, dest)

            for name in list(sys.modules):
                if name == "worlds.oot" or name.startswith("worlds.oot."):
                    del sys.modules[name]

            ap_handler = handler.ApHandler(supported, custom)
            world_source = MagicMock()
            world_source.load.side_effect = [False, True]

            with patch.object(handler, "WorldSource", return_value=world_source):
                with patch.object(ap_handler, "load_apworld") as load_peer:
                    missing = ModuleNotFoundError("No module named 'worlds.oot'")
                    missing.name = "worlds.oot"
                    with patch(
                        "handler.importlib.import_module",
                        side_effect=missing,
                    ):
                        ap_handler._load_world_from_zip(dest, "child")
                        load_peer.assert_called_once_with("oot", "0.6.7")
                        self.assertEqual(world_source.load.call_count, 2)


class LoadApworldPeerTests(unittest.TestCase):
    def test_load_tww3_with_bundled_oot(self):
        if os.environ.get("RUN_APWORLD_INTEGRATION") != "1":
            self.skipTest("set RUN_APWORLD_INTEGRATION=1 to run Archipelago integration tests")

        try:
            import handler  # noqa: E402
        except ModuleNotFoundError as exc:
            self.skipTest(f"handler dependencies unavailable: {exc}")

        tww3_path = os.environ.get("TWW3_APWORLD_PATH", "/tmp/tww3.apworld")
        if not os.path.isfile(tww3_path):
            self.skipTest(f"tww3 apworld not available at {tww3_path}")

        supported = os.environ["AP_SUPPORTED_WORLDS_DIR"]
        custom = os.environ.get("AP_CUSTOM_WORLDS_DIR", tempfile.mkdtemp())
        shutil.copy(tww3_path, os.path.join(custom, "tww3-0.11.0.apworld"))

        # Match production worker images: core worlds exist only as apworld zips.
        oot_dir = os.environ.get("ARCHIPELAGO_WORLDS_DIR", "/tmp/ap-integ/archipelago/worlds/oot")
        if os.path.isdir(oot_dir):
            shutil.rmtree(oot_dir)

        ap_handler = handler.ApHandler(supported, custom)
        ap_handler.load_apworld("tww3", "0.11.0")

        self.assertIn("worlds.oot", sys.modules)
        self.assertIn("worlds.tww3", sys.modules)
        # client.py imports tracker but options-gen only needs the world import graph.
        self.assertNotIn("worlds.tracker", sys.modules)


if __name__ == "__main__":
    unittest.main()
