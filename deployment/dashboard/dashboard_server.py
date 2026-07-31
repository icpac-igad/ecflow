#!/usr/bin/env python3
"""E4DRR ecFlow GIK monitor — dependency-free.
Serves dashboard.html and reverse-proxies /api/* -> ecflow_http :8080 /v1/*
(same-origin, so the browser makes no cross-origin calls). stdlib only."""
import http.server, urllib.request, urllib.error, os, re, json, shutil, threading, time

ECFLOW = os.environ.get("ECFLOW_HTTP", "http://localhost:8080/v1")
ROOT   = os.path.dirname(os.path.abspath(__file__))
PORT   = int(os.environ.get("DASH_PORT", "8090"))
BIND   = os.environ.get("DASH_BIND", "0.0.0.0")
ECF_LOG = os.environ.get("ECF_LOG", "/home/hkoros/e4drr-ecflow/data/e4drr-ecflow.3141.ecf.log")
SUITE   = os.environ.get("GIK_SUITE", "ecmwf_ifs_gik")
JOB_DIR = os.environ.get("GIK_JOB_DIR", "/home/hkoros/e4drr-ecflow/data/%s/day" % SUITE)
RUN_LOGS = os.path.join(ROOT, "run_logs")
STAGE_NAMES = ["discover", "lithops_parquet", "icechunk_append", "publish_mirror"]

def _runkey(r):
    return r["start"].replace("-", "").replace(":", "").replace(" ", "_")

def archive_latest(runs):
    """Snapshot the current stage job-logs into a per-run archive, once, so past
    runs remain viewable after ecFlow overwrites its live .1 files on the next run."""
    if not runs:
        return
    r = runs[0]  # most recent
    d = os.path.join(RUN_LOGS, _runkey(r))
    if os.path.isdir(d):
        return
    try:
        os.makedirs(d, exist_ok=True)
        for s in STAGE_NAMES:
            src = os.path.join(JOB_DIR, s + ".1")
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(d, s + ".log"))
    except Exception:
        pass

_LINE = re.compile(
    r"\[(\d\d):(\d\d):(\d\d) (\d\d)\.(\d\d)\.(\d{4})\]\s+(active|complete|aborted|queued):\s+(/" + SUITE + r"\S*)")

def parse_runs(limit=30):
    """Reconstruct run history from the ecFlow log: each family cycle = one run,
    bounded by the suite-level complete/aborted transition."""
    try:
        lines = open(ECF_LOG, errors="ignore").read().splitlines()[-12000:]
    except Exception:
        return []
    runs, cur = [], None
    def close(cur, ts):
        cur["end"] = ts
        cur["state"] = "failed" if any(t == "failed" for t in cur["tasks"].values()) else "completed"
        runs.append(cur)
    for ln in lines:
        m = _LINE.search(ln)
        if not m:
            continue
        hh, mm, ss, dd, mo, yy, state, node = m.groups()
        ts = "%s-%s-%s %s:%s:%s" % (yy, mo, dd, hh, mm, ss)
        segs = node.strip("/").split("/")
        if len(segs) == 3:  # /suite/day/<task>
            task = segs[2]
            if state == "active":
                if cur is None:
                    cur = {"start": ts, "end": ts, "tasks": {}}
                cur["tasks"][task] = "running"; cur["end"] = ts
            elif state == "complete" and cur:
                cur["tasks"][task] = "completed"; cur["end"] = ts
            elif state == "aborted" and cur:
                cur["tasks"][task] = "failed"; cur["end"] = ts
        elif len(segs) == 1 and state in ("complete", "aborted") and cur:
            close(cur, ts); cur = None
    if cur:
        cur["state"] = "running"; runs.append(cur)
    out = runs[-limit:][::-1]
    for r in out:
        r["key"] = _runkey(r)
    archive_latest(out)
    return out


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(ROOT, "dashboard.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, str(e), "text/plain")
            return
        if path == "/runs":
            self._send(200, json.dumps(parse_runs())); return
        if path == "/runlog":
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            key = (q.get("run") or [""])[0]
            stage = (q.get("stage") or [""])[0]
            if not re.match(r"^[0-9_]+$", key or ""):
                self._send(400, "bad request"); return
            base = os.path.join(RUN_LOGS, key)
            def read(s):
                f = os.path.join(base, s + ".log")
                if os.path.exists(f):
                    try:
                        with open(f, encoding="utf-8", errors="ignore") as fh:
                            return fh.read()
                    except Exception:
                        return None
                return None
            if not os.path.isdir(base):
                self._send(200, "Logs were not retained for this run.\n"
                                "(Per-run log archiving began after this run; newer runs keep their logs.)\n",
                           "text/plain; charset=utf-8"); return
            if stage in STAGE_NAMES:            # single stage
                c = read(stage)
                self._send(200, c if c is not None else "(no log for this stage)\n",
                           "text/plain; charset=utf-8"); return
            # combined single log — all stages in flow order
            labels = {"discover": "L1 · DISCOVER", "lithops_parquet": "L2 · LITHOPS PARQUET",
                      "icechunk_append": "L3 · ICECHUNK APPEND", "publish_mirror": "L4 · PUBLISH MIRROR"}
            parts = []
            for s in STAGE_NAMES:
                c = read(s)
                parts.append("========== %s ==========\n%s" % (labels[s], c if c is not None else "(no log)\n"))
            self._send(200, "\n".join(parts), "text/plain; charset=utf-8")
            return
        if path.startswith("/api/"):
            url = ECFLOW + "/" + path[len("/api/"):]
            if "?" in self.path:
                url += "?" + self.path.split("?", 1)[1]
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    self._send(200, r.read(), r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                self._send(e.code, e.read(), "application/json")
            except Exception as e:
                self._send(502, '{"error":"%s"}' % str(e).replace('"', "'"))
            return
        self._send(404, '{"error":"not found"}')

    def log_message(self, *a):
        pass


def _archiver():
    """Archive every run's logs promptly, independent of browser activity, so logs
    are never lost when ecFlow overwrites its live .1 files on the next run."""
    while True:
        try:
            parse_runs()      # calls archive_latest() on the most recent run
        except Exception:
            pass
        time.sleep(10)


if __name__ == "__main__":
    threading.Thread(target=_archiver, daemon=True).start()
    srv = http.server.ThreadingHTTPServer((BIND, PORT), H)
    print(f"E4DRR ecFlow dashboard on http://{BIND}:{PORT}  (proxying {ECFLOW})", flush=True)
    srv.serve_forever()
