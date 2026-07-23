"""Panel<->backend contract anchor (pure — no DB).

The committed JSON schema in panel/contract/ is the pinned wire shape of the
queue snapshot. If someone changes the response model, this fails and reminds
them to regenerate the file AND update panel/app/lib/types.ts to match.

Regenerate with:
    python -c "import json,pathlib; from app.api.schemas import QueueSnapshot; \
      pathlib.Path('../panel/contract/queue-snapshot.schema.json').write_text( \
      json.dumps(QueueSnapshot.model_json_schema(), indent=2, sort_keys=True)+chr(10))"
"""

from __future__ import annotations

import json
import pathlib

from app.api.schemas import QueueSnapshot

_SCHEMA_FILE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "panel"
    / "contract"
    / "queue-snapshot.schema.json"
)


def test_committed_schema_matches_live_model():
    assert _SCHEMA_FILE.exists(), f"missing committed schema at {_SCHEMA_FILE}"
    committed = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    live = QueueSnapshot.model_json_schema()
    assert committed == live, (
        "queue snapshot response shape drifted from the committed contract — "
        "regenerate panel/contract/queue-snapshot.schema.json and update "
        "panel/app/lib/types.ts to match."
    )


def test_snapshot_field_names_are_exactly_the_panel_type():
    """Guards the top-level field set the panel's QueueSnapshot TS type reads."""
    props = set(QueueSnapshot.model_json_schema()["properties"].keys())
    assert props == {"session", "now_serving", "entries", "sessions", "can_undo"}
