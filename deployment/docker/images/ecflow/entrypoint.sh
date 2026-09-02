#!/usr/bin/env bash
# Role dispatcher. The same image runs the engine, the REST proxy or the UDP
# ingress; compose picks the role via the command.
set -euo pipefail

role="${1:-server}"
shift || true

# ecFlow resolves the calling uid to a user name and aborts if it cannot
# ("UserCmd::get_user: could not determine user name for uid N"). We run as the
# host's uid so bind-mounted state stays host-owned, which means that uid is
# absent from the image's /etc/passwd. Add it. Requires group 0 membership,
# granted by compose via group_add; the fallback keeps the image usable when it
# is run without that.
if ! getent passwd "$(id -u)" >/dev/null 2>&1; then
  printf 'ecflow:x:%s:%s:ecFlow:%s:/bin/bash\n' \
    "$(id -u)" "$(id -g)" "${ECF_HOME}" >> /etc/passwd 2>/dev/null \
    || echo "WARN: could not add passwd entry for uid $(id -u); ecFlow may refuse to start" >&2
fi
export USER="${USER:-ecflow}" LOGNAME="${LOGNAME:-ecflow}"

case "$role" in
  server)
    # The stateful singleton. Configured entirely through the environment —
    # ecflow_server has no command-line options beyond --help (`ecflow_server
    # --help` lists only ECF_PORT / ECF_HOME / ECF_LOG / ECF_CHECK etc.), so do
    # not add flags here expecting them to take effect.
    #
    # ecflow_server restores its checkpoint on boot but comes up HALTED (an ecFlow
    # safety default), so scheduling — and thus the daily cron — would stay paused
    # after any container restart until an operator resumes it. To keep the daily
    # workflow uninterrupted across restarts, start the server, wait for it to
    # answer, then resume it to RUNNING. The script stays PID 1 and forwards signals
    # so Docker still owns the lifecycle (ecflow_start.sh is still avoided: it nohups
    # the process, leaving the container with nothing to supervise).
    cd "${ECF_HOME}"
    ecflow_server &
    srv=$!
    trap 'kill -TERM "$srv" 2>/dev/null' TERM INT
    port="${ECF_PORT:-3141}"
    for _ in $(seq 1 30); do
      if ecflow_client --host=localhost --port="$port" --ping >/dev/null 2>&1; then
        ecflow_client --host=localhost --port="$port" --restart >/dev/null 2>&1 \
          && echo "entrypoint: ecflow_server resumed to RUNNING (post-checkpoint restore)" >&2 \
          || echo "WARN: could not resume ecflow_server to RUNNING; scheduling may be halted" >&2
        break
      fi
      sleep 1
    done
    wait "$srv"
    ;;

  http)
    # Stateless REST proxy. --no_ssl is the default here because the only route
    # in is an SSH tunnel or the private tailnet; turn it off (and add
    # --tokens_file) before binding this anywhere wider.
    exec ecflow_http \
      --ecflow_host="${ECF_HOST}" \
      --ecflow_port="${ECF_PORT}" \
      --port="${ECF_HTTP_PORT:-8080}" \
      --no_ssl \
      ${ECF_HTTP_ARGS:-}
    ;;

  udp)
    exec ecflow_udp \
      --ecflow_host="${ECF_HOST}" \
      --ecflow_port="${ECF_PORT}" \
      --port="${ECF_UDP_PORT:-19999}" \
      ${ECF_UDP_ARGS:-}
    ;;

  shell)
    exec bash
    ;;

  *)
    # Anything else runs verbatim, so `docker compose run ecflow-server
    # ecflow_client --stats` works without a dedicated role.
    exec "$role" "$@"
    ;;
esac
