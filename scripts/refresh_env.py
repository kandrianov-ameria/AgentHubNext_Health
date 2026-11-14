"""
Regenerate .env from the build secrets of agent-hub-backend.

Since AgentHubNext 4.0.64 the credentials are no longer hardcoded in the source.
The app compiles them in from the developer's local, git-ignored
`secrets.local.txt` in the repository root (build/Secrets.targets,
secrets.local.example.txt). This script reads that same file.

Run this ONLY when a credential has been rotated. Normal test runs never touch
the repository - they read .env and suite.env.

    python scripts/refresh_env.py [path-to-agent-hub-backend]
    python scripts/refresh_env.py [path-to-agent-hub-backend] --secrets path\to\secrets.local.txt

What it writes:
  .env       the credentials only (gitignored). Values already set there for the
             optional TWO_D_TO_*_BASIC_AUTH keys are kept.
  suite.env  the base URLs are compared with the source; a URL that changed in
             the source is updated in place (suite.env is committed, so the
             change shows up in git). Nothing else in suite.env is touched.

It refuses to write .env when any of the four values is missing, empty or still
the build placeholder (__AGENTHUB_SECRET_<NAME>__), so a half-filled
secrets.local.txt can never replace a working .env.
"""
import re
import sys
from pathlib import Path

DEFAULT_REPO = Path(r"D:\MAVERICK\_AgentHubNext\agent-hub-backend")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

RCM = "src/AgentHub/RemoteConfiguration/RemoteConfigurationManager.cs"
ITS = "src/Ameria.LlmExecutionEngine/Services/ImageTo3DAgentSettings.cs"
GLB = "src/AgentHub/Global.cs"

SECRETS_FILE_NAME = "secrets.local.txt"

# .env key -> placeholder name in secrets.local.txt (BuildSecret items in
# src/AgentHub/AgentHub.csproj and src/Ameria.LlmExecutionEngine/Ameria.LlmExecutionEngine.csproj).
SECRETS = {
    # RemoteConfigurationManager.WindowsApiToken. The template says the value is the full
    # Authorization header ("Bearer <id>|<token>"); the suite adds "Bearer " itself, so a
    # leading "Bearer " is removed here.
    "AIHUB_WIN_TOKEN": "AIHUB_SERVICE_AUTH_WINDOWS",
    # ImageTo3DAgentSettings.MavStarkitApiKey (X-API-Key)
    "STARKIT_API_KEY": "MAVSTARKIT_API_KEY",
    # ImageTo3DAgentSettings.DeviceMappingBearerToken ("<id>|<token>", without "Bearer ")
    "AIHUB_DEVICE_MAPPING_TOKEN": "DEVICE_MAPPING_BEARER_TOKEN",
    # Global.cs WriteTo.Seq(apiKey: ...)
    "SEQ_API_KEY": "AGENTHUB_SEQ_API_KEY",
}
# AIHUB_SERVICE_AUTH_MAC is also in the file; the Windows suite does not use it.

PLACEHOLDER_PREFIX = "__AGENTHUB_SECRET_"

URLS = {
    "AIHUB_SERVICE_BASE_URL":
        (RCM, r'OperatingSystem\.IsWindows\(\)\s*\r?\n?\s*\?\s*"([^"]+)"'),
    "MAV_STARKIT_BASE_URL":
        (ITS, r'MavStarkitApiBaseUrl\s*\{\s*get;\s*set;\s*\}\s*=\s*\r?\n?\s*"([^"]+)"'),
    "TWO_D_TO_3D_BASE_URL":
        (ITS, r'TwoDToThreeDBaseUrl\s*\{\s*get;\s*set;\s*\}\s*=\s*\r?\n?\s*"([^"]+)"'),
    "TWO_D_TO_VIDEO_BASE_URL":
        (ITS, r'\?\?\s*"(https://[^"]*2d-to-video[^"]*)"'),
    "DEVICE_MAPPING_BASE_URL":
        (ITS, r'DeviceMappingBaseUrl\s*\{\s*get;\s*set;\s*\}\s*=\s*\r?\n?\s*"([^"]+)"'),
    "SEQ_BASE_URL":
        (GLB, r'WriteTo\.Seq\(\s*"([^"]+)"'),
}


def extract(repo: Path, table: dict) -> dict:
    out, missing = {}, []
    cache = {}
    for name, (rel, pattern) in table.items():
        path = repo / rel
        if rel not in cache:
            if not path.exists():
                missing.append(f"{name}: file not found - {rel}")
                continue
            cache[rel] = path.read_text(encoding="utf-8-sig", errors="replace")
        m = re.search(pattern, cache[rel])
        if not m:
            missing.append(f"{name}: pattern did not match in {rel}")
            continue
        out[name] = m.group(1).strip()
    if missing:
        print("EXTRACTION PROBLEMS:", *missing, sep="\n  ")
    return out


def read_secrets_file(path: Path) -> dict:
    """Parse secrets.local.txt exactly as build/Secrets.targets does:
    trimmed lines, '#' comments, name = text before the first '=', value = the rest."""
    out = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq <= 0:
            continue
        out[line[:eq].strip()] = line[eq + 1:].strip()
    return out


def load_secrets(secrets_file: Path) -> dict:
    """Return {.env key: value}; prints the problems and returns what it could read."""
    if not secrets_file.exists():
        print(f"SECRETS FILE NOT FOUND: {secrets_file}\n"
              f"  AgentHubNext no longer keeps credentials in its source. Copy "
              f"secrets.local.example.txt to {SECRETS_FILE_NAME} in the repository root and "
              f"fill it in (ask the team lead for the values), or pass --secrets <path>.")
        return {}
    raw = read_secrets_file(secrets_file)
    out, problems = {}, []
    for env_key, name in SECRETS.items():
        v = raw.get(name, "")
        if not v:
            problems.append(f"{env_key}: {name} is missing or empty in {secrets_file.name}")
        elif v.startswith(PLACEHOLDER_PREFIX):
            problems.append(f"{env_key}: {name} is still a build placeholder")
        else:
            if env_key == "AIHUB_WIN_TOKEN":
                v = re.sub(r"^Bearer\s+", "", v, flags=re.IGNORECASE)
            out[env_key] = v
    if problems:
        print("SECRETS PROBLEMS:", *problems, sep="\n  ")
    return out


def mask(v: str) -> str:
    return f"{'*' * 8}{v[-4:]}" if len(v) > 8 else "*" * len(v)


OPTIONAL = ["TWO_D_TO_3D_BASIC_AUTH", "TWO_D_TO_VIDEO_BASIC_AUTH"]


def read_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def update_suite_urls(urls: dict) -> list:
    """Set changed base URLs in suite.env in place. Returns (name, old, new) per change."""
    path = PROJECT_ROOT / "suite.env"
    if not path.exists():
        print(f"\nsuite.env not found at {path} - restore it from the repository.")
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    changes, seen = [], set()
    for i, line in enumerate(lines):
        k, sep, v = line.partition("=")
        k = k.strip()
        if sep and k in urls and not line.lstrip().startswith("#"):
            seen.add(k)
            if v.strip() != urls[k]:
                changes.append((k, v.strip(), urls[k]))
                lines[i] = f"{k}={urls[k]}"
    for k in urls:
        if k not in seen:
            changes.append((k, "(missing)", urls[k]))
            lines.append(f"{k}={urls[k]}")
    if changes:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changes


def parse_args(argv: list) -> tuple:
    repo, secrets_file, rest = None, None, list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--secrets" and rest:
            secrets_file = Path(rest.pop(0))
        elif repo is None:
            repo = Path(a)
    repo = repo or DEFAULT_REPO
    return repo, secrets_file or (repo / SECRETS_FILE_NAME)


def main() -> int:
    repo, secrets_file = parse_args(sys.argv[1:])
    if not repo.exists():
        print(f"Repository not found: {repo}")
        return 2

    secrets = load_secrets(secrets_file)
    urls = extract(repo, URLS)

    if len(secrets) != len(SECRETS):
        print("\nRefusing to write an incomplete .env; the existing .env was not changed.")
        return 1

    env_path = PROJECT_ROOT / ".env"
    kept = read_env_file(env_path)
    lines = [
        "# AgentHubNext health suite - credentials",
        "# GENERATED by scripts/refresh_env.py from the build secrets file",
        "# (secrets.local.txt) of agent-hub-backend. Re-run it only after a rotation.",
        "#",
        "# THIS FILE CONTAINS LIVE PRODUCTION CREDENTIALS. It is gitignored.",
        "# Do not commit it, paste it, or attach it to a ticket.",
        "# Base URLs, the environment name and other non-secret settings are in suite.env.",
        "",
        "# ---- credentials (from secrets.local.txt) ---------------------------",
    ]
    for k in SECRETS:
        lines.append(f"{k}={secrets[k]}")
    lines += [
        "",
        "# ---- optional -------------------------------------------------------",
        "# 2d-to-3d has no credentials in source (auth disabled by default).",
        "# 2d-to-video reads these from the environment; empty means no auth header.",
    ]
    for k in OPTIONAL:
        lines.append(f"{k}={kept.get(k, '')}")
    lines.append("")
    env_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nWrote {env_path} (from {secrets_file})")
    print("\n  credentials (masked):")
    for k in SECRETS:
        print(f"    {k:<28} {mask(secrets[k])}")
    for k in OPTIONAL:
        print(f"    {k:<28} {'(kept, ' + mask(kept[k]) + ')' if kept.get(k) else '(empty)'}")

    changes = update_suite_urls(urls)
    print("\n  base URLs in suite.env:")
    if not changes:
        print("    unchanged - they match the source")
    for k, old, new in changes:
        print(f"    {k:<28} {old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
