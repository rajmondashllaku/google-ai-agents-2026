"""Optional helper for listing Gemini models; not used by the simulator."""

from __future__ import annotations

import os


def main() -> int:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit(
            "GOOGLE_API_KEY is not set. The offline simulator does not require it."
        )
    try:
        from google import genai
    except ImportError as exc:
        raise SystemExit(
            'Install the optional helper dependency with: pip install "google-genai>=1,<2"'
        ) from exc

    client = genai.Client(api_key=api_key)
    for model in client.models.list():
        name = model.name.lower()
        if "pro" in name or "flash" in name:
            print(model.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
