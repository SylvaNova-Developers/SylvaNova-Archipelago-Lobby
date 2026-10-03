from opentelemetry import trace
import requests
import shutil
import tempfile
import os
import sys
import zipfile
import zipimport
import json
import importlib
import importlib.abc
import importlib.machinery
import glob
from pathlib import Path

from apworld_peers import PEER_WORLD_EXCLUDED, discover_peer_world_imports  # noqa: E402

ap_path = os.path.abspath(os.path.dirname(sys.argv[0]))
sys.path.insert(0, ap_path)

# Register a custom finder to allow dynamic apworld loading
# This is needed because upstream's APWorldModuleFinder doesn't expose its spec dict
_dynamic_apworld_specs = {}

class _DynamicAPWorldFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, _path=None, _target=None):
        return _dynamic_apworld_specs.get(fullname)

sys.meta_path.insert(0, _DynamicAPWorldFinder())

from worlds import WorldSource  # noqa: E402
from worlds.AutoWorld import AutoWorldRegister  # noqa: E402
from worlds.Files import APWorldContainer, InvalidDataError  # noqa: E402
from Utils import tuplize_version, init_logging  # noqa: E402
import worlds  # noqa: E402
import settings  # noqa: E402

# Headless workers must never open a file browser for required UserFolderPath settings.
settings.no_gui = True


# Some **supported** apworlds try to get stuff from external APIs. We do not want that as it currently times out in prod
# Until I have a better solution, just return an error immediately when someone tries to use requests
def no_internet(*args, **kwargs):
    raise RuntimeError("The apworld tried to contact the internet which isn't supported with YAML validation.")

requests.get = no_internet
requests.post = no_internet
requests.put = no_internet
requests.head = no_internet
requests.options = no_internet
requests.delete = no_internet

tracer = trace.get_tracer("ap-handler")

class ApHandler:
    def __init__(self, apworlds_dir, custom_apworlds_dir):
        self.apworlds_dir = apworlds_dir
        self.custom_apworlds_dir = custom_apworlds_dir
        self.refresh_netdata_package()
        self.tempdir = tempfile.mkdtemp()

    def __del__(self):
        shutil.rmtree(self.tempdir)

    def check_apworld_directory_name(self, apworld_path, apworld_name):
        with zipfile.ZipFile(apworld_path, "r") as zf:
            for name in zf.namelist():
                parts = name.split('/')
                if len(parts) > 1 and parts[0] == apworld_name:
                    return

            root_dirs = {name.split('/')[0] for name in zf.namelist() if '/' in name}
            raise Exception(f"Apworld must contain a directory named '{apworld_name}'. Found: {sorted(root_dirs)}")

    def read_apworld_manifest(self, apworld_path):
        """
        Read the archipelago.json manifest from an apworld file.
        Returns a tuple of (game_name, world_version) or (None, None) if not found.

        We have to use a custom method here instead of `APWorldContainer` because
        core world manifests don't have a `compatible_version` in sources, it
        only gets put there when they build AP. So we assume that manifests without
        one are core and if they're not the I tried my best.
        """
        with zipfile.ZipFile(apworld_path, "r") as zf:
            for info in zf.infolist():
                if info.filename.endswith("archipelago.json"):
                    with zf.open(info, "r") as f:
                        manifest = json.load(f)

                    # If compatible_version is present, validate it
                    if "compatible_version" in manifest:
                        container_version = APWorldContainer.version
                        if manifest["compatible_version"] > container_version:
                            raise Exception(
                                f"Apworld requires container version "
                                f"{manifest['compatible_version']} but we only support {container_version}"
                            )

                    world_game = manifest.get("game")
                    world_version = None
                    if "world_version" in manifest:
                        try:
                            world_version = tuplize_version(manifest["world_version"])
                        except:
                            # Version string is not in expected format (e.g., "alpha02b")
                            # Leave as None, world will use default 0.0.0
                            pass

                    return world_game, world_version

        return None, None

    def _resolve_apworld_file(self, apworld_name, apworld_version):
        custom_apworld_path = (
            f"{self.custom_apworlds_dir}/{apworld_name}-{apworld_version}.apworld"
        )
        if os.path.isfile(custom_apworld_path):
            return custom_apworld_path

        supported_apworld_path = (
            f"{self.apworlds_dir}/{apworld_name}-{apworld_version}.apworld"
        )
        if os.path.isfile(supported_apworld_path):
            return supported_apworld_path

        return None

    def _find_bundled_apworld(self, apworld_name):
        """
        Locate a bundled apworld zip when only the world name is known (e.g. peer dependency).
        """
        for base_dir in (self.custom_apworlds_dir, self.apworlds_dir):
            pattern = os.path.join(base_dir, f"{apworld_name}-*.apworld")
            matches = sorted(glob.glob(pattern))
            if not matches:
                continue
            path = matches[-1]
            version = os.path.basename(path)[len(apworld_name) + 1 : -len(".apworld")]
            return path, version

        return None, None

    def _peer_from_module_error(self, error):
        name = getattr(error, "name", None)
        if not name or not name.startswith("worlds."):
            return None

        parts = name.split(".")
        if len(parts) < 2:
            return None

        peer = parts[1]
        if peer in PEER_WORLD_EXCLUDED:
            return None

        return peer

    def _unload_world_module(self, world_module):
        prefix = f"worlds.{world_module}"
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                del sys.modules[name]

        try:
            worlds.failed_world_loads.remove(world_module)
        except ValueError:
            pass

    def _peer_needed_for_failed_load(self, dest_path, apworld_name, world_module):
        """
        WorldSource.load() logs import errors and returns False instead of raising.
        Re-import the world module to recover the missing peer package name.
        """
        self._unload_world_module(world_module)
        try:
            importlib.import_module(f"worlds.{world_module}")
            return None
        except ModuleNotFoundError as error:
            peer = self._peer_from_module_error(error)
            if peer is not None:
                return peer
        except Exception:
            pass

        for peer in sorted(discover_peer_world_imports(dest_path, apworld_name)):
            if f"worlds.{peer}" not in sys.modules:
                return peer

        return None

    def _load_peer_for_world(self, apworld_name, peer):
        if f"worlds.{peer}" in sys.modules:
            return

        peer_path, peer_version = self._find_bundled_apworld(peer)
        if peer_path is None:
            raise Exception(
                f"Apworld '{apworld_name}' requires worlds.{peer}, but no apworld for "
                f"'{peer}' was found under {self.apworlds_dir} or {self.custom_apworlds_dir}"
            )

        self.load_apworld(peer, peer_version)

    def _load_world_from_zip(self, dest_path, apworld_name, max_peer_loads=16):
        loads = 0
        world_module = Path(dest_path).stem
        while True:
            loaded = WorldSource(dest_path, is_zip=True, relative=False).load()
            if loaded:
                return

            peer = self._peer_needed_for_failed_load(dest_path, apworld_name, world_module)
            if peer is None:
                if f"worlds.{world_module}" in sys.modules:
                    return
                raise Exception(f"Failed to load apworld '{apworld_name}'")

            if loads >= max_peer_loads:
                raise Exception(
                    f"Failed to load apworld '{apworld_name}' after loading peer worlds"
                )

            loads += 1
            self._load_peer_for_world(apworld_name, peer)
            self._unload_world_module(world_module)

    @tracer.start_as_current_span("load_apworld")
    def load_apworld(self, apworld_name, apworld_version):
        span = trace.get_current_span()
        span.set_attribute("apworld_name", apworld_name)
        span.set_attribute("apworld_version", apworld_version)

        if '/' in apworld_name:
            raise Exception("Invalid apworld name")

        if '/' in apworld_version:
            raise Exception("Invalid apworld version")

        if f"worlds.{apworld_name}" in sys.modules:
            return

        source_apworld_path = self._resolve_apworld_file(apworld_name, apworld_version)
        dest_path = f"{self.tempdir}/{apworld_name}.apworld"

        if source_apworld_path is None:
            raise Exception(
                "Invalid apworld: {}, version {}".format(apworld_name, apworld_version)
            )

        shutil.copy(source_apworld_path, dest_path)

        world_game, world_version = self.read_apworld_manifest(dest_path)

        # Register the module spec so WorldSource.load() can find it
        world_name = Path(dest_path).stem
        importer = zipimport.zipimporter(dest_path)
        spec = importer.find_spec(f"worlds.{world_name}")
        _dynamic_apworld_specs[f"worlds.{world_name}"] = spec

        self._load_world_from_zip(dest_path, apworld_name)

        if world_game and world_game in AutoWorldRegister.world_types:
            if world_version:
                AutoWorldRegister.world_types[world_game].world_version = world_version

        self.refresh_netdata_package()

    def refresh_netdata_package(self):
        for world_name, world in AutoWorldRegister.world_types.items():
            if world_name not in worlds.network_data_package["games"]:
                worlds.network_data_package["games"][world_name] =  world.get_data_package_data()


