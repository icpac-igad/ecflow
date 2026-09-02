#!/usr/bin/env python3
"""E4DRR ecFlow GIK monitor — dependency-free.
Serves dashboard.html and reverse-proxies /api/* -> ecflow_http :8080 /v1/*
(same-origin, so the browser makes no cross-origin calls). stdlib only."""
import http.server, urllib.request, urllib.error, os, re, json, shutil, threading, time

ECFLOW = os.environ.get("ECFLOW_HTTP", "http://localhost:8080/v1")
ROOT   = os.path.dirname(os.path.abspath(__file__))
PORT   = int(os.environ.get("DASH_PORT", "8090"))
BIND   = os.environ.get("DASH_BIND", "0.0.0.0")
# Host-specific paths are env-driven; real values live in the private deploy repo.
ECF_DATA = os.environ.get("ECF_DATA_DIR", "/path/to/ecflow/data")
ECF_LOG = os.environ.get("ECF_LOG", "%s/e4drr-ecflow.3141.ecf.log" % ECF_DATA)
SUITE   = os.environ.get("GIK_SUITE", "ecmwf_ifs_gik")
JOB_DIR = os.environ.get("GIK_JOB_DIR", "%s/%s/day" % (ECF_DATA, SUITE))
RUN_LOGS = os.environ.get("RUN_LOGS", os.path.join(ROOT, "run_logs"))
INDEX    = os.path.join(RUN_LOGS, "index.json")
STAGE_NAMES = ["discover", "lithops_parquet", "icechunk_append", "publish_mirror"]
_lock = threading.Lock()

def _runkey(r):
    return r["start"].replace("-", "").replace(":", "").replace(" ", "_")

def _load_index():
    """Persistent record of every run ever seen — the source of truth for /runs, so
    history is never lost when a run scrolls out of the ecFlow log's rolling window."""
    try:
        with open(INDEX) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_index(idx):
    try:
        os.makedirs(RUN_LOGS, exist_ok=True)
        tmp = INDEX + ".tmp"
        with open(tmp, "w") as f:
            json.dump(idx, f)
        os.replace(tmp, INDEX)          # atomic, so a reader never sees a half-written file
    except Exception:
        pass

def _archive_logs(r):
    """Snapshot the current .1 job-logs for run r into run_logs/<key>/. Called on the
    newest run each cycle, so a run first seen mid-flight is refreshed to completion
    before ecFlow overwrites its .1 files on the next run."""
    d = os.path.join(RUN_LOGS, r["key"])
    try:
        os.makedirs(d, exist_ok=True)
        for s in r.get("tasks", {}):
            src = os.path.join(JOB_DIR, s + ".1")
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(d, s + ".log"))
    except Exception:
        pass

def _bootstrap_index():
    """Seed the index from run_logs/ dirs already on disk (from before the index
    existed, or from runs that have since scrolled out of the log), so every archived
    run stays visible in /runs. Runs are keyed YYYYMMDD_HHMMSS."""
    with _lock:
        idx = _load_index()
        changed = False
        try:
            entries = os.listdir(RUN_LOGS)
        except Exception:
            entries = []
        for key in entries:
            d = os.path.join(RUN_LOGS, key)
            if key in idx or not re.match(r"^\d{8}_\d{6}$", key) or not os.path.isdir(d):
                continue
            tasks = {}
            for s in STAGE_NAMES:
                if os.path.exists(os.path.join(d, s + ".log")):
                    tasks[s] = "completed"
            start = "%s-%s-%s %s:%s:%s" % (key[0:4], key[4:6], key[6:8], key[9:11], key[11:13], key[13:15])
            idx[key] = {"start": start, "end": start, "tasks": tasks,
                        "state": "completed", "key": key, "bootstrapped": True}
            changed = True
        if changed:
            _save_index(idx)

def sync_runs(limit=200):
    """Parse the rolling log window, merge into the persistent index (old runs are
    never dropped), archive the newest run's logs, and return all runs newest-first."""
    parsed = parse_runs()               # newest-first, from the log's tail window
    with _lock:
        idx = _load_index()
        for r in parsed:
            k = r["key"]
            old = idx.get(k)
            # take the newer view unless it's a partial re-parse of an already-terminal run
            if old is None or r["state"] != "running" or len(r.get("tasks", {})) >= len(old.get("tasks", {})):
                if not (old and old.get("state") != "running" and r["state"] == "running"):
                    idx[k] = r
        _save_index(idx)
        allruns = sorted(idx.values(), key=lambda x: x["start"], reverse=True)[:limit]
    if parsed:
        _archive_logs(parsed[0])        # refresh the newest run's per-stage logs
    return allruns

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
            self._send(200, json.dumps(sync_runs())); return
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
    """Continuously merge runs into the persistent index and archive their logs,
    independent of browser activity. Never dies: every iteration is guarded, so one
    bad parse can't stop archiving. Paired with systemd Restart=always, past runs and
    their logs are retained across the process's whole lifetime and restarts."""
    while True:
        try:
            sync_runs()
        except Exception:
            pass
        time.sleep(10)


if __name__ == "__main__":
    _bootstrap_index()      # make already-archived runs visible on startup
    threading.Thread(target=_archiver, daemon=True).start()
    srv = http.server.ThreadingHTTPServer((BIND, PORT), H)
    print(f"E4DRR ecFlow dashboard on http://{BIND}:{PORT}  (proxying {ECFLOW})", flush=True)
    srv.serve_forever()
