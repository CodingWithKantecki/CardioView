"""A server whose strap is fake: the recording streamed like the H10 (kind live, from zero, no
preroll). For checking Strap / Demo switching and the lost state without hardware:

    python tools/fake_strap.py            # http://localhost:8002

Never on port 8000: that is the real server Thomas judges on.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.sources.base import PREROLL_S  # noqa: E402
from backend.sources.replay import ReplaySource  # noqa: E402
from backend.sources.rhythm import RhythmSource  # noqa: E402

RECORDING = Path(__file__).resolve().parent.parent / "data" / "h10_ecg_thomas.csv"


class FakeStrap(ReplaySource):
    kind = "live"

    def __init__(self):
        super().__init__(RECORDING)
        self.status.device = "Polar H10 FAKE"


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8002
    app = create_app({"live": FakeStrap,
                      "demo": lambda: ReplaySource(RECORDING, preroll_s=PREROLL_S),
                      "rhythm": lambda pattern="sinus": RhythmSource(pattern, preroll_s=PREROLL_S)}, "live")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
