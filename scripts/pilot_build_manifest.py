"""Record internal native build provenance without reading credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=("android", "windows", "ios-simulator"))
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    args = parser.parse_args()
    origin = os.environ.get("REACT_APP_BACKEND_URL", "")
    url = urlsplit(origin)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment or origin != f"https://{url.netloc}"
            or url.hostname.endswith(".invalid")):
        raise SystemExit("An explicit HTTPS API origin without credentials/path/query is required")
    if not args.bundle_dir.is_dir() or not any(
        origin.encode() in path.read_bytes() for path in args.bundle_dir.rglob("*.js")
    ):
        raise SystemExit("Packaged renderer does not contain the approved API origin")
    extensions = {"android": ".apk", "windows": ".exe", "ios-simulator": ".zip"}
    artifacts = sorted(args.artifact_dir.glob("*" + extensions[args.platform]))
    if not artifacts:
        raise SystemExit("No native artifact was produced")
    files = []
    for path in artifacts:
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        files.append({"filename": path.name, "sizeBytes": path.stat().st_size, "sha256": digest})
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = {
        "channel": "internal-pilot",
        "platform": args.platform,
        "sourceCommit": commit,
        "apiOrigin": origin,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "storeRelease": False,
        "signing": {"android": "debug key", "windows": "unsigned",
                    "ios-simulator": "unsigned simulator only"}[args.platform],
        "artifacts": files,
    }
    (args.artifact_dir / "build-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (args.artifact_dir / "README.txt").write_text(
        f"NUA POS internal pilot — {args.platform}\n"
        f"Source: {commit}\nAPI: {origin}\n"
        f"Signing: {manifest['signing']}\n\n"
        "This is an internal test package, not a signed merchant/store release.\n"
        "It connects to the real NUA service. Use the correct venue account.\n"
        "Do not run automated financial acceptance tests against this origin.\n"
        "Use a separately provisioned test venue for supervised pilot transactions.\n"
        "iOS Simulator builds require a Mac with Xcode and cannot install on an iPhone/iPad.\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
