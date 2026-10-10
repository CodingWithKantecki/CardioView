"""A download cut short resumes where it stopped and never passes a short file off as complete."""
import io

from research.rhythm import download as dl

PAYLOAD = bytes(range(256)) * 40


class Response(io.BytesIO):
    def __init__(self, body, status, length):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def serve(monkeypatch, tmp_path, honour_range=True):
    calls = []

    def urlopen(req, timeout):
        rng = req.get_header("Range")
        calls.append(rng)
        if rng is None:
            return Response(PAYLOAD[:3000], 200, len(PAYLOAD))   # the connection drops early, no error
        if not honour_range:
            return Response(PAYLOAD, 200, len(PAYLOAD))
        start = int(rng.split("=")[1].rstrip("-"))
        return Response(PAYLOAD[start:], 206, len(PAYLOAD) - start)

    monkeypatch.setattr(dl, "DATA", tmp_path)
    monkeypatch.setattr(dl.urllib.request, "urlopen", urlopen)
    return calls


def test_a_transfer_cut_short_resumes_where_it_stopped(tmp_path, monkeypatch):
    calls = serve(monkeypatch, tmp_path)
    path = dl.fetch("file.bin", "https://example.org/file.bin")
    assert path.read_bytes() == PAYLOAD and calls == [None, "bytes=3000-"]


def test_a_server_that_ignores_the_range_starts_over_cleanly(tmp_path, monkeypatch):
    serve(monkeypatch, tmp_path, honour_range=False)
    assert dl.fetch("file.bin", "https://example.org/file.bin").read_bytes() == PAYLOAD


def test_mirror_fetches_what_is_missing_and_retries_a_short_body(tmp_path, monkeypatch):
    bodies = {"https://x/a.dat": b"abcdef", "https://x/b.hea": b"hea"}
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        body = bodies[req.full_url]
        if req.full_url.endswith("a.dat") and calls.count(req.full_url) == 1:
            return Response(body[:3], 200, len(body))   # cut short: tried again
        return Response(body, 200, len(body))

    monkeypatch.setattr(dl.urllib.request, "urlopen", urlopen)
    (tmp_path / "c.hea").write_bytes(b"there")
    jobs = {tmp_path / "sub" / "a.dat": "https://x/a.dat", tmp_path / "b.hea": "https://x/b.hea",
            tmp_path / "c.hea": "https://x/c.hea"}
    assert dl.mirror(jobs, workers=2) == 2
    assert (tmp_path / "sub" / "a.dat").read_bytes() == b"abcdef" and (tmp_path / "b.hea").read_bytes() == b"hea"
    assert "https://x/c.hea" not in calls
