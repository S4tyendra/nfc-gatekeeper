# NFC Gatekeeper // Production Deployment Manual

**Target:** Debian 12 (Bookworm)

**User:** `nfc`

**App Dir:** `/opt/nfc-gatekeeper`

**Data Dir:** `/var/lib/iiitk-nfc`

> ⚠️ **WARNING:** This setup modifies kernel modules, nukes the login screen, and deletes system binaries. Do not run this on a general-purpose workstation.

## 1\. System Prep & Kernel Blacklist

We need to stop the kernel from grabbing the NFC reader so `pcscd` can have it exclusively. We also need to tell Polkit to shut up and let us work.

```bash
# 1. Blacklist conflicting kernel modules
sudo bash -c 'cat << EOF > /etc/modprobe.d/nfc-blacklist.conf
blacklist nfc
blacklist pn533
blacklist pn533_usb
EOF'

# 2. Allow 'nfc' user to control pcscd without auth prompts
sudo bash -c 'cat << EOF > /etc/polkit-1/rules.d/99-nfc-pcscd.rules
polkit.addRule(function(action, subject) {
    if (subject.user == "nfc") {
        return polkit.Result.YES;
    }
});
EOF'

# 3. Update & Install Dependencies
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl build-essential libpcsclite-dev swig python3-dev \
    python3-full python3-pip chromium lightdm openbox unclutter pcscd

# 4. Enable PC/SC Daemon
sudo systemctl enable pcscd
sudo systemctl start pcscd
```

## 2\. App Installation (`/opt`)

We are deploying to `/opt` because we aren't running a hobby project here.

```bash
# 1. Install UV (Fast Python Pkg Manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env

# 2. Clone & Permissions
cd /opt
sudo git clone https://github.com/S4tyendra/nfc-gatekeeper.git
sudo chown -R nfc:nfc /opt/nfc-gatekeeper

# 3. Setup Python Environment
cd /opt/nfc-gatekeeper
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## 3\. Data Directory Setup

The OS owns `/var/lib`. We hijack it now.

```bash
sudo mkdir -p /var/lib/iiitk-nfc/databases
sudo mkdir -p /var/lib/iiitk-nfc/images
sudo chown -R nfc:nfc /var/lib/iiitk-nfc/
```

## 4\. Backend Service (Systemd)

This keeps the Python API alive.

Create `/etc/systemd/system/nfc-gatekeeper.service`:

```ini
[Unit]
Description=NFC Gatekeeper Backend Service
After=network.target pcscd.service pcscd.socket
Requires=pcscd.service pcscd.socket

[Service]
Type=simple
User=nfc
Group=nfc
WorkingDirectory=/opt/nfc-gatekeeper
ExecStartPre=/bin/sleep 2
ExecStart=/opt/nfc-gatekeeper/.venv/bin/python /opt/nfc-gatekeeper/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable & Start:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable nfc-gatekeeper
sudo systemctl start nfc-gatekeeper
```

## 5\. Kiosk Frontend (Scorched Earth)

### A. LightDM Auto-Login & Insomnia

Edit `/etc/lightdm/lightdm.conf`. Find the `[Seat:*]` section and force these settings:

```ini
[Seat:*]
autologin-user=nfc
autologin-user-timeout=0
# God-mode command to disable X server sleep/DPMS
xserver-command=X -s 0 -dpms
```

### B. Chromium Autostart (No Keyring)

Create `~/.config/autostart/kiosk.desktop`. The `--password-store=basic` flag is non-negotiable to avoid popups.

```bash
mkdir -p ~/.config/autostart
cat << EOF > ~/.config/autostart/kiosk.desktop
[Desktop Entry]
Type=Application
Name=Gatekeeper Kiosk
Exec=chromium --kiosk --no-first-run --incognito --disable-restore-session-state --password-store=basic http://localhost:8080
StartupNotify=false
Terminal=false
Hidden=false
EOF
```

### C. Delete Keyrings (Destructive)

Ensure the OS *cannot* ask for a password.

```bash
# 1. Delete any existing keys
rm -rf ~/.local/share/keyrings

# 2. Delete the daemon binaries so they never run
sudo rm -f /usr/bin/gnome-keyring /usr/bin/gnome-keyring-3 /usr/bin/gnome-keyring-daemon
```

## 6\. Final Verification

1.  **Backend:** `sudo systemctl status nfc-gatekeeper` should be active (green).
2.  **Reader:** `pcsc_scan` should see your reader (Ctrl+C to exit).
3.  **Reboot:** `sudo reboot`.
