"""The Export menu's PDF report: the page's buffer becomes a saved summary with a link and a QR."""
import asyncio

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.sources.base import FS, Packet, Source
from backend.synth import synth_session


class Quiet(Source):
    kind = "live"

    async def packets(self):
        self.set_status("connecting")
        await asyncio.sleep(3600)
        yield Packet(0.0, [])


def test_export_report_makes_a_saved_summary(tmp_path):
    ses = synth_session(seed=2)
    uv = [int(v) for v in ses.uv[: 40 * FS]]
    with TestClient(create_app({"demo": Quiet}, "demo", sessions_dir=tmp_path)) as c:
        r = c.post("/api/export/report", json={"fs": FS, "t0": 12.5, "uv": uv, "source": "recorded", "device": "Recording x"})
        assert r.status_code == 200, r.text
        sid, link = r.json()["id"], r.json()["link"]
        assert link.endswith(f"/s/{sid}")
        s = c.get(f"/api/s/{sid}").json()
        assert s["export"] is True and s["seconds"] == 40 and s["source"] == "recorded"
        assert s["steps"] == [{"name": "export", "start": 0.0, "end": 40.0}]
        assert s["hrv"]["ok"] and s["beat"]["ok"] and s["hr_chart"]["bpm"], "the whole stretch measures as one resting window"
        assert c.get(f"/api/s/{sid}/qr.svg").status_code == 200
        assert (tmp_path / sid / "ecg.csv").read_text().count("\n") == len(uv) + 1, "the samples are stored like a session"
        assert c.get(f"/s/{sid}").status_code == 200


def test_export_report_refuses_too_little(tmp_path):
    with TestClient(create_app({"demo": Quiet}, "demo", sessions_dir=tmp_path)) as c:
        assert c.post("/api/export/report", json={"fs": FS, "t0": 0, "uv": [0] * 100}).status_code == 409
        assert c.post("/api/export/report", json={"uv": "nope"}).status_code == 400
