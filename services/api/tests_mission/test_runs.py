import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import runs_service as rs


def test_stats_and_csv(tmp_path, monkeypatch):
    f = tmp_path / "runs.jsonl"
    rows = [
        {"started": "2026-11-19T10:00:00", "route": "lab_tour", "kind": "tour", "result": "done",
         "duration_s": 300, "length_m": 37, "progress": 1, "blocked_s": 10, "blocked_at": [[1, 2]],
         "alignment": {"used": True, "dx": 0.03, "dy": -0.04, "dyaw_deg": 2.0, "fit": 0.9}},
        {"started": "2026-11-19T11:00:00", "route": "lab_tour", "kind": "tour", "result": "aborted",
         "duration_s": 60, "length_m": 37, "progress": 0.3, "blocked_s": 0, "alignment": {"used": False}},
        {"started": "2026-11-19T12:00:00", "route": "lab_tour", "kind": "tour", "result": "cancelled",
         "duration_s": 5, "length_m": 37, "progress": 0, "blocked_s": 0},
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    monkeypatch.setattr(rs, "META_FILE", str(tmp_path / "meta.json"))
    runs = rs.load_runs(str(f))
    assert len(runs) == 3
    s = rs.stats(runs)
    assert s["success_rate"] == 0.5 and s["avg_duration_s"] == 300 and s["alignment"]["avg_shift_cm"] == 5.0
    rs.set_meta(runs[1]["id"], "test run, tablet offline", True)
    runs = rs.load_runs(str(f))
    s = rs.stats(runs)
    assert s["excluded"] == 1 and s["success_rate"] == 1.0
    csv = rs.to_csv(runs)
    assert csv.splitlines()[0].startswith("started,route") and "tablet offline" in csv
