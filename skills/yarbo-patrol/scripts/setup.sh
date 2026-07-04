#!/usr/bin/env bash
# Initial environment setup for the yarbo-patrol module.
# Works on Linux, macOS, Raspberry Pi, and Termux (Android).
set -euo pipefail

say() { printf '\n==> %s\n' "$*"; }

ON_TERMUX=0
if [ -n "${PREFIX:-}" ] && case "$PREFIX" in *com.termux*) true ;; *) false ;; esac; then
    ON_TERMUX=1
fi

if [ "$ON_TERMUX" = 1 ]; then
    say "Termux detected - installing base packages"
    pkg install -y python git termux-api >/dev/null
else
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 not found - install Python 3.10+ first" >&2
        exit 1
    fi
fi

PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
say "Python $PYVER found"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
    echo "Python 3.10+ required (found $PYVER)" >&2
    exit 1
}

say "Installing python-yarbo"
python3 -m pip install --upgrade python-yarbo

say "Verifying the library imports"
python3 -c 'import yarbo; print("python-yarbo OK")'

say "Setup complete"
cat <<'EOF'

Next steps (see rules/setup-and-connectivity.md for details):

  1. Find the base station IP in your router's client list
     (MAC prefix C8:FE:0F) and give it a static DHCP lease.

  2. Read-only connectivity check (robot does NOT move):
       python3 check_connection.py --broker <ip> --sn <serial>

  3. Safe command test - buzzer + lights, still no movement:
       python3 command_test.py --broker <ip> --sn <serial>

  4. Create a short 'patrol-test' plan in the Yarbo app, then run
     your first supervised patrol:
       python3 patrol_controller.py --broker <ip> --sn <serial> \
           --plan patrol-test --expected-runtime 300 --lights -v

EOF

if [ "$ON_TERMUX" = 1 ]; then
    cat <<'EOF'
Termux notes:
  - Run 'termux-wake-lock' before any patrol so Android does not
    suspend the watchdog mid-run.
  - Exclude Termux from battery optimization in Android settings.
  - Auto-discovery needs raw sockets and will not work unrooted;
    always pass --broker explicitly.
EOF
fi
