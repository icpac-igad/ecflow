#!/usr/bin/env python3
"""GIK host executor — bridges the isolated ecFlow container to the host pipeline.

The ecFlow server runs in a minimal container (no icechunk/lithops, no view of
~/gikvenv). Its jobs have curl, so they call this whitelisted HTTP service on the
host, which runs pipeline commands in the real venv and returns output + the exit
code as HTTP status (200 ok / 500 failed) so the ecFlow task aborts correctly.

Era handling follows ECFLOW_50R1_OPERATIONALIZATION.md — BOTH switches must agree:
  switch 1 = era ENV (ECMWF_CONTROL_STREAM / ECMWF_REFERENCE_DATE) -> which S3 bytes are read
  switch 2 = runtime: tag in lithops_config.yaml                   -> which template decodes them
49r1 (<= 2026-05-12): enfo / 20240529.   50r1 (>= 2026-05-13): oper / 20260513.

Whitelisted stages only. Bound to the docker-bridge gateway. stdlib only."""
import http.server, subprocess, os, urllib.parse

# All host-specific paths are env-driven — set these in the systemd unit (see
# systemd/gik-executor.service.example). Real values live in the private deploy repo.
PIPE = os.environ.get("GIK_PIPE_DIR", "/path/to/cno-e4drr/devops/lithops_cr_ecmwf_gik")
PY   = os.environ.get("GIK_VENV_PY", "/path/to/gikvenv/bin/python")
KEY  = os.environ.get("GIK_SA_KEY", PIPE + "/service_account/<sa-key>.json")
PORT = int(os.environ.get("EXEC_PORT", "8091"))
BIND = os.environ.get("EXEC_BIND", "172.18.0.1")  # docker-bridge gateway on the host

DISCOVER = (
    "import gcsfs, s3fs, sys\n"
    "fs = gcsfs.GCSFileSystem(token=%r)\n"
    "ls = fs.ls('gik-ecmwf-aws-tf/run_par_ecmwf')\n"
    "print('GCS store reachable: %%d dated dirs under run_par_ecmwf/' %% len(ls))\n"
    "s3 = s3fs.S3FileSystem(anon=True)\n"
    "p = 'ecmwf-forecasts/%s/00z/ifs/0p25/enfo/'\n"
    "avail = s3.exists(p)\n"
    "print('S3 00z run for %s:', 'AVAILABLE' if avail else 'not published yet')\n"
    "sys.exit(0 if ls else 1)\n"
)

def era_for(date):
    if date and date < "20260513":
        return "49r1", "enfo", "20240529"
    return "50r1", "oper", "20260513"

def command_for(stage, q):
    date = (q.get("date") or [""])[0]
    run  = (q.get("run") or ["00"])[0]
    if stage == "discover":
        return [PY, "-c", DISCOVER % (KEY, date, date)]
    if stage == "lithops_parquet":
        era, stream, refdate = era_for(date)
        script = (
            "set -e; cp lithops_config.yaml /tmp/_cfg.bak; "
            "sed 's#runtime: gcr.io/e4drr-crafd/ecmwf-lithops-runtime.*#"
            "runtime: gcr.io/e4drr-crafd/ecmwf-lithops-runtime:%s#' /tmp/_cfg.bak > lithops_config.yaml; "
            "export ECMWF_CONTROL_STREAM=%s ECMWF_REFERENCE_DATE=%s ECMWF_RESOLUTION=0p25 "
            "GCS_PARQUET_PREFIX=v20260623_run_par_ecmwf; "
            "echo \"[era %s] stream=%s refdate=%s runtime=:%s date=%s\"; "
            "%s run_lithops_ecmwf.py --date %s --run %s --max-workers 5 --yes; rc=$?; "
            "cp /tmp/_cfg.bak lithops_config.yaml; exit $rc"
            % (era, stream, refdate, era, stream, refdate, era, date, PY, date, run)
        )
        return ["bash", "-c", script]
    return None

class H(http.server.BaseHTTPRequestHandler):
    def reply(self, code, body):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        try: self.wfile.write(b)
        except BrokenPipeError: pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/health":
            self.reply(200, "gik-executor ok\n"); return
        parts = u.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "run":
            q = urllib.parse.parse_qs(u.query)
            cmd = command_for(parts[1], q)
            if not cmd:
                self.reply(404, "unknown stage: %s\n" % parts[1]); return
            try:
                r = subprocess.run(cmd, cwd=PIPE, capture_output=True, text=True, timeout=1800,
                                   env={**os.environ, "GOOGLE_APPLICATION_CREDENTIALS": KEY})
                out = (r.stdout or "") + (r.stderr or "")
                self.reply(200 if r.returncode == 0 else 500,
                           out + "\n[stage %s exit %d]\n" % (parts[1], r.returncode))
            except subprocess.TimeoutExpired:
                self.reply(500, "stage %s timed out\n" % parts[1])
            except Exception as e:
                self.reply(500, "executor error: %s\n" % e)
            return
        self.reply(404, "not found\n")

    def log_message(self, *a): pass

if __name__ == "__main__":
    print("gik-executor on http://%s:%d  (pipeline=%s)" % (BIND, PORT, PIPE), flush=True)
    http.server.ThreadingHTTPServer((BIND, PORT), H).serve_forever()
