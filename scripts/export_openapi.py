"""Write the API's OpenAPI schema to a file, for generating the web app's TypeScript types.

    uv run python scripts/export_openapi.py apps/web/src/api/openapi.json

Needs no database or model: the app creates those on first use.
"""

import json
import sys
from pathlib import Path

from shelfwise.api.main import create_app
from shelfwise.config import Settings


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "apps/web/src/api/openapi.json")
    schema = create_app(Settings(log_json=False)).openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {out} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
