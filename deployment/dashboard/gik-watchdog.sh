#!/usr/bin/env bash
# Self-healing watchdog for the daily GIK ecFlow suite.
#
# The daily suite can get stuck `aborted` — an abort that ecFlow does not auto-requeue —
# which silently halts the daily run until someone intervenes (this once went unnoticed
# for a month). Run on a timer, this watchdog un-sticks it:
#   * server HALTED/SHUTDOWN          -> --restart  (resume scheduling)
#   * suite suspended                 -> --resume
#   * suite aborted                   -> --requeue + --resume + clear RUN_DATE
# A cooldown caps requeues so a genuinely-failing day is not re-run on every tick. It
# does nothing when the suite is healthy. Safe to run frequently; idempotent.
set -euo pipefail

SUITE="${GIK_SUITE:-ecmwf_ifs_gik}"
CONTAINER="${ECFLOW_CONTAINER:-e4drr-ecflow-server}"
PORT="${ECF_PORT:-3141}"
COOLDOWN_H="${WATCHDOG_COOLDOWN_H:-12}"             # min hours between requeues
STATE="${WATCHDOG_STATE:-$HOME/.gik-watchdog-last-requeue}"

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
dk() { docker exec "$CONTAINER" ecflow_client --host=localhost --port="$PORT" "$@"; }

if ! dk --ping >/dev/null 2>&1; then
  echo "$(ts) watchdog: ecFlow server unreachable (container=$CONTAINER) — skipping"
  exit 0
fi

# 1) scheduling halted -> restart
svr=$(dk --stats 2>/dev/null | grep -i 'Status' | grep -oE 'RUNNING|HALTED|SHUTDOWN' | head -1 || true)
if [[ "$svr" == "HALTED" || "$svr" == "SHUTDOWN" ]]; then
  echo "$(ts) watchdog: server $svr -> --restart"
  dk --restart >/dev/null 2>&1 || true
fi

line=$(dk --get_state "/$SUITE" 2>/dev/null | grep -E "^suite $SUITE " || true)
state=$(printf '%s' "$line" | grep -oE 'state:[a-z]+' | cut -d: -f2 || true)
suspended=$(printf '%s' "$line" | grep -c 'suspended:1' || true)

# 2) suspended -> resume (cheap, does not trigger a run)
if [[ "$suspended" == "1" ]]; then
  echo "$(ts) watchdog: /$SUITE suspended -> --resume"
  dk --resume "/$SUITE" >/dev/null 2>&1 || true
fi

# 3) aborted -> requeue, with cooldown
if [[ "$state" == "aborted" ]]; then
  now=$(date -u +%s)
  last=$(cat "$STATE" 2>/dev/null || echo 0)
  age_h=$(( (now - last) / 3600 ))
  if (( age_h >= COOLDOWN_H )); then
    echo "$(ts) watchdog: /$SUITE ABORTED (last requeue ${age_h}h ago) -> requeue + resume"
    dk --requeue force "/$SUITE"                         >/dev/null 2>&1 || true
    dk --resume "/$SUITE"                                >/dev/null 2>&1 || true
    dk --alter=change variable RUN_DATE "" "/$SUITE/day" >/dev/null 2>&1 || true
    echo "$now" > "$STATE"
    echo "$(ts) watchdog: recovered /$SUITE -> queued"
  else
    echo "$(ts) watchdog: /$SUITE aborted but requeued ${age_h}h ago (< ${COOLDOWN_H}h cooldown) — waiting"
  fi
else
  echo "$(ts) watchdog: /$SUITE healthy (state=${state:-unknown}) — no action"
fi
