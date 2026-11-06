#!/usr/bin/env bash
# Sentinel - user-level installer (no root required).
#
#   ./install.sh            install deps + desktop entry (+ systemd timer)
#   ./install.sh --no-timer skip the systemd timer
#
# What it does:
#   1. installs the Python dependencies (into the active virtualenv, or
#      --user when none is active)
#   2. registers the app so it shows up in your application menu
#      (~/.local/share/applications + icon)
#   3. optionally installs the daily 03:00 systemd backup timer
#      (~/.config/systemd/user) - the schedule itself is configured in the
#      app and can be edited later with `systemctl --user edit`

set -euo pipefail

cd "$(dirname "$0")"

WITH_TIMER=1
if [[ "${1:-}" == "--no-timer" ]]; then
    WITH_TIMER=0
fi

# --- 1. Python dependencies -------------------------------------------------
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo ">> Installing dependencies into the active virtualenv"
    pip install -r requirements.txt
    BIN_DIR="$VIRTUAL_ENV/bin"
else
    echo ">> No virtualenv active - installing with pip --user"
    pip install --user -r requirements.txt
    BIN_DIR="$HOME/.local/bin"
fi

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/sentinel" <<EOF
#!/usr/bin/env bash
exec python3 "$(pwd)/run.py" "\$@"
EOF
chmod +x "$BIN_DIR/sentinel"
echo ">> Installed launcher: $BIN_DIR/sentinel"

# --- 2. Desktop entry --------------------------------------------------------
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
cp data/icons/sentinel.png "$HOME/.local/share/icons/hicolor/256x256/apps/sentinel.png"
cp data/sentinel.desktop "$HOME/.local/share/applications/sentinel.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo ">> Added to your application menu"

# --- 3. Systemd timer (optional) --------------------------------------------
if [[ $WITH_TIMER -eq 1 ]] && command -v systemctl >/dev/null; then
    mkdir -p "$HOME/.config/systemd/user"
    cp data/systemd/sentinel-backup.service "$HOME/.config/systemd/user/"
    sed "s|%h/.local/bin/sentinel|$BIN_DIR/sentinel|" \
        data/systemd/sentinel-backup.service \
        > "$HOME/.config/systemd/user/sentinel-backup.service"
    cp data/systemd/sentinel-backup.timer "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    systemctl --user enable --now sentinel-backup.timer 2>/dev/null || true
    echo ">> Daily 03:00 backup timer enabled (systemctl --user list-timers)"
fi

echo
echo "Done! Start Sentinel from your application menu, or run: sentinel"
