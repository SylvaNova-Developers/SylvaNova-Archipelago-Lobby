import re
import zipfile

# worlds.* packages that ship with the Archipelago install (not as apworld zips).
PEER_WORLD_EXCLUDED = frozenset({"generic", "AutoWorld", "LauncherComponents"})
_WORLD_IMPORT_RE = re.compile(
    r"(?:from|import)\s+worlds\.([a-zA-Z_][a-zA-Z0-9_]*)"
)


def discover_peer_world_imports(apworld_path, apworld_name):
    """
    Return other world package names imported from Python sources inside an apworld zip.

    Some indexed apworlds (e.g. tww3) import helpers from core worlds such as Ocarina of Time
    (`worlds.oot`). Those worlds are removed from the Archipelago tree in worker images and only
    exist as bundled apworld zips under supported_worlds, so they must be loaded explicitly.
    """
    peers = set()
    with zipfile.ZipFile(apworld_path, "r") as zf:
        for info in zf.infolist():
            if not info.filename.endswith(".py"):
                continue
            with zf.open(info) as f:
                text = f.read().decode("utf-8", errors="replace")
            for match in _WORLD_IMPORT_RE.finditer(text):
                peer = match.group(1)
                if peer == apworld_name or peer in PEER_WORLD_EXCLUDED:
                    continue
                peers.add(peer)
    return peers
