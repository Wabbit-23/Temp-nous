#!/usr/bin/env bash
# Helper to start a noVNC stack inside the container.
# Starts Xvfb, fluxbox (optional), x11vnc and websockify (serving /opt/noVNC).
# Logs are written to logs/novnc.log. Use the Codespaces Ports panel to open :6080.

set -euo pipefail
mkdir -p logs

logfile="logs/novnc.log"
echo "[run-novnc] logfile=$logfile"

echo "[run-novnc] stopping any previous services..." | tee -a "$logfile"
pkill -f websockify || true
pkill -f novnc_proxy || true
pkill -f x11vnc || true
pkill -f fluxbox || true
pkill -f Xvfb || true
sleep 0.3

echo "[run-novnc] starting Xvfb on :99..." | tee -a "$logfile"
Xvfb :99 -screen 0 1280x720x24 >>"$logfile" 2>&1 &
export DISPLAY=:99
sleep 0.3

echo "[run-novnc] starting fluxbox (optional WM)..." | tee -a "$logfile"
fluxbox >>"$logfile" 2>&1 &
sleep 0.3

echo "[run-novnc] starting x11vnc on :99 (rfbport 5900)..." | tee -a "$logfile"
# start without password for quick testing; change to -rfbauth ~/.vnc/passwd for production
x11vnc -display :99 -nopw -forever -shared -rfbport 5900 >>"$logfile" 2>&1 &
sleep 0.3

echo "[run-novnc] starting websockify (noVNC) on :6080..." | tee -a "$logfile"
# Prefer system python to avoid venv/module mismatches
if command -v /usr/bin/python3 >/dev/null 2>&1; then
  PY=/usr/bin/python3
else
  PY=$(command -v python3 || true)
fi
if [ -z "${PY:-}" ]; then
  echo "[run-novnc] ERROR: python3 not found" | tee -a "$logfile"
  exit 1
fi

WEBROOT=/opt/noVNC
if [ ! -d "$WEBROOT" ]; then
  echo "[run-novnc] warning: noVNC web root not found at $WEBROOT" | tee -a "$logfile"
  echo "[run-novnc] please clone noVNC into /opt/noVNC or adjust WEBROOT in this script." | tee -a "$logfile"
fi

echo "[run-novnc] running: $PY -m websockify --web $WEBROOT 6080 localhost:5900" | tee -a "$logfile"
nohup "$PY" -m websockify --web "$WEBROOT" 6080 localhost:5900 >>"$logfile" 2>&1 &

echo "[run-novnc] all services started. Tail the logfile with: tail -f $logfile" | tee -a "$logfile"
echo "[run-novnc] In Codespaces: open the Ports panel and 'Open in Browser' for port 6080." | tee -a "$logfile"
echo "[run-novnc] Then visit: http://<forwarded-host>:6080/vnc.html?host=127.0.0.1&port=5900&autoconnect=1" | tee -a "$logfile"

exit 0
