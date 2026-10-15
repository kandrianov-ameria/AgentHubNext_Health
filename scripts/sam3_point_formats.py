"""
One-off diagnostic: send the SAM3 point request in both coordinate formats.

  A = format documented in the segmentation service README  (point_coords=100,60   point_labels=1)
  B = format Sam3Client.SegmentByPointAsync sends           (point_coords=[[100,60]] point_labels=[1])

SamPredictUrl and ProxyAuthHeader are read from pat-config with the token in .env,
so no secret has to be typed or printed. Run from the project root:

    .venv\\Scripts\\python scripts\\sam3_point_formats.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agenthub_health import redact, remote, settings  # noqa: E402
from agenthub_health.probe import call  # noqa: E402

VARIANTS = {
    "A (README format)": {"point_coords": "100,60", "point_labels": "1"},
    "B (Sam3Client format)": {"point_coords": "[[100,60]]", "point_labels": "[1]", "mask_threshold": "0.5"},
}


def main() -> int:
    fetch, section = remote.agenthub_section()
    if not fetch.probe.ok or section is None:
        print("Could not read the AgentHub section of pat-config:", redact.text(fetch.probe.error or fetch.probe.http_status))
        return 2
    url = str(section.get("SamPredictUrl") or "")
    auth = str(section.get("ProxyAuthHeader") or "")
    redact.register(auth)
    if not url:
        print("SamPredictUrl is not set for", settings.env_name())
        return 2
    image = (settings.ASSETS_DIR / "probe.jpg").read_bytes()
    print(f"Environment {settings.env_name()}, POST {url}\n")
    for name, fields in VARIANTS.items():
        res = call("sam3", name, "POST", url, headers={"Authorization": auth} if auth else {},
                   data={"return_zip": "false", **fields},
                   files={"image_file": ("screen.jpg", image, "image/jpeg")}, timeout=60, record=False)
        code = res.http_status if res.http_status is not None else res.status.value
        print(f"{name}: HTTP {code} after {res.latency_ms} ms")
        print("  ", redact.text((res.body or res.error or "")[:300]).replace("\n", " "), "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
