# AGENTS.md

## Cursor Cloud specific instructions

These notes are for agents working on the **Archipelago lobby** repo in the Cursor Cloud
environment (dependencies already installed by the startup/update script). They capture the
non-obvious bits of running the app locally. Standard build/run docs live in `README.md`.

### What this repo is
A Cargo workspace. The player-facing product is the `lobby` crate (`ap-lobby`), a Rocket web
app backed by **PostgreSQL** and **Valkey/Redis**. Python workers under `ap-worker/`
(`yaml-checker`, `generator`, `option-generator`) embed the real Archipelago engine and talk to
the lobby over Valkey-backed job queues. Other crates: `apwm` (index/apworld manager), `wq`
(work-queue lib), `common`, `apdiff-viewer` (standalone PR-diff viewer), `community-ap-tools`.
The sibling repo `SylvaNova-archipelago-index` is the apworld **data/index** the lobby consumes.

### Toolchain gotcha (important)
The workspace needs a Rust toolchain that supports **edition 2024** (Rust ≥ 1.85); the image's
default `1.83` fails with `feature edition2024 is required`. `rustup default stable` is set during
setup — verify with `rustc --version` and re-run `rustup default stable` if you get that error.

### Running services (no systemd in this container)
Postgres and Valkey are installed but must be started manually each session:
```
sudo pg_ctlcluster 16 main start          # Postgres 16 (compose pins 17; 16 is fine for dev)
valkey-server --daemonize yes --port 6379 --save ""
```
The `aplobby` database and `postgres`/`postgres` credentials are created during setup. The
lobby runs its Diesel migrations automatically at startup, so a fresh DB self-populates.

### Running the lobby in dev mode (native, no Docker)
The documented path (`README.md`) is Docker Compose, but the lobby builds and runs natively,
which is lighter for iterating. It reads config from env vars **and** a gitignored `Rocket.toml`
(Discord OAuth section is required to exist, but placeholder values are fine unless you need real
login). Minimal working env:
```
DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/aplobby
VALKEY_URL=redis://127.0.0.1:6379?protocol=resp3
ADMIN_TOKEN=changeme
ROCKET_SECRET_KEY=<44/88 base64 or 64 hex chars>   # required to keep sessions stable
GENERATION_OUTPUT_DIR=/tmp/gen-output
APWORLDS_INDEX_REPO_URL=/agent/repos/SylvaNova-archipelago-index   # local clone; avoids network
APWORLDS_INDEX_REPO_BRANCH=main
APWORLDS_INDEX_DIR=/tmp/apworlds_index
APWORLDS_PATH=/tmp/apworlds_index/worlds
SKIP_APWORLDS_UPDATE=1        # skip downloading ~470 apworlds on boot (slow); index is still cloned
YAML_VALIDATION_QUEUE_TOKEN=changeme
GENERATION_QUEUE_TOKEN=changeme
OPTIONS_GEN_QUEUE_TOKEN=changeme
ROCKET_ADDRESS=127.0.0.1
```
Then `cargo run --bin ap-lobby`. Health check: `curl http://127.0.0.1:8000/health` →
`{"status":"healthy",...}`. Note `IndexManager::new()` always clones the index repo even when
`SKIP_APWORLDS_UPDATE` is set — pointing `APWORLDS_INDEX_REPO_URL` at the local index repo keeps
it offline and fast.

Production deployments should set `APWORLDS_INDEX_REPO_URL` to
`https://github.com/SylvaNova-Developers/SylvaNova-Archipelago-Index.git` (see
`docker-compose.yml.example`). The lobby does not poll the index; after merges,
call `GET /worlds/refresh` with `X-Api-Key: $ADMIN_TOKEN`, or rely on the index
repo's post-merge workflow once `LOBBY_REFRESH_URL` / `LOBBY_ADMIN_TOKEN` secrets
are set there.

### The Python workers are heavy / optional for lobby dev
`yaml-checker` and `generator` need the full Archipelago engine (built via
`taskcluster/docker/ap-worker/Dockerfile` — clones + cythonizes Archipelago). They are **not**
needed to exercise the lobby's room + YAML-submission flow: create a room with
`yaml_validation = false` and YAML uploads are stored without contacting a worker.

### Auth caveat for testing (no live Discord)
Login normally requires **Discord OAuth**. Two ways to test protected flows without it:
- Admin API: send `X-Api-Key: $ADMIN_TOKEN` (or Basic `admin:$ADMIN_TOKEN`). This grants an
  admin session but with `user_id = None`, so routes that call `session.user_id()` (create room,
  upload YAML, templates) will panic — it only works for admin-only API endpoints.
- Forge a logged-in session cookie: since you control `ROCKET_SECRET_KEY`, encrypt a
  `session` JSON (`{"is_admin":true,"is_logged_in":true,"user_id":<id>,"redirect_on_login":null,"uuid":"<uuid>"}`)
  with the `cookie` crate (v0.18, `Key::from` when the key is 64 bytes) and send it as the
  `session` cookie. Insert the user first: `INSERT INTO discord_users (id, username) VALUES (...)`.
  In a browser, the server's own `session` cookie is **HttpOnly**, so `document.cookie` can't
  replace it — edit it via DevTools → Application → Cookies instead.

### Lint / test / build
Standard Cargo commands from the repo root (all pass): `cargo clippy --workspace --all-targets`,
`cargo test --workspace` (the `wq` tests spawn their own `valkey-server`), `cargo build --bin ap-lobby`.
`cargo fmt --check` currently reports a pre-existing diff in `apdiff-viewer/src/api/mod.rs`.
