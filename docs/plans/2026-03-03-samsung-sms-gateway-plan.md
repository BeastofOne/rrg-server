# Samsung Tablet Residential SMS Gateway — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Set up a Samsung Galaxy Tab E 8.0 (SM-T377A, Android 6.0.1) as a dedicated residential lead SMS gateway, splitting SMS traffic from the existing Pixel 9a (commercial only).

**Architecture:** Two-device SMS gateway setup. Pixel 9a handles commercial leads (Crexi/LoopNet/BizBuySell) via Tailscale IP. Samsung tablet handles residential leads (Realtor.com/Seller Hub/Social Connect/UpNest) via local WiFi IP. Both run Termux + Flask with identical `/send-sms` endpoint contracts. Windmill post-approval modules select gateway per-draft based on `source_type`.

**Tech Stack:** Android 6.0.1, Termux (legacy Android 5/6 build), Python, Flask (or stdlib fallback), ADB, Windmill (Python scripts)

**Device:** Samsung Galaxy Tab E 8.0 (SM-T377A), SIM: (734) 808-1176, ADB ID: `520396edf478738d`

**Tablet static IP:** `192.168.1.250` (adjust if your LAN uses a different subnet)

---

## Phase 1: Device Validation (Showstopper Gate)

These tasks validate that the tablet CAN run the gateway. If any fails, stop and fall back to MacroDroid approach.

---

### Task 1: Install Termux on the Samsung Tablet

**Context:** Modern Termux requires Android 7+. This tablet runs Android 6.0.1, so we need the legacy build. All three APKs (Termux, Termux:API, Termux:Boot) must come from the same source (same signing key) or they won't interoperate.

**Files:** None (device-only)

**Step 1: Download Termux APKs for Android 5/6**

Check the official Termux CI builds first (preferred), then Qiamast fork as fallback.

Run from jake-macbook:
```bash
# Option A: Official CI builds (apt-android-5 variant)
# Go to https://github.com/termux/termux-app/actions and download latest apt-android-5 build
# Also need matching Termux:API and Termux:Boot from their respective repos

# Option B: Qiamast Marshmallow fork
curl -L -o /tmp/termux-marshmallow.apk "https://github.com/Qiamast/Termux_Marshmallow/releases/latest/download/termux-app_marshmallow-debug.apk"
```

Check https://github.com/Qiamast/Termux_Marshmallow/releases for the latest APK filename — it may differ.

**Step 2: Install Termux APK on tablet**

```bash
adb install /tmp/termux-marshmallow.apk
```

Expected: `Success`

If signature conflict: `adb uninstall com.termux` first, then retry.

**Step 3: Open Termux on tablet and verify it launches**

```bash
adb shell am start -n com.termux/.HomeActivity
```

Expected: Termux terminal opens on the tablet screen. Wait ~30 seconds for initial bootstrap.

**Step 4: Install Termux:API (same-source APK)**

Download from the same source as the Termux app (matching signing key).

```bash
adb install /tmp/termux-api.apk
```

Expected: `Success`

If you get `INSTALL_FAILED_SHARED_USER_INCOMPATIBLE`, the signing keys don't match. Try a different source for all three APKs.

**Step 5: Install Termux:Boot (same-source APK)**

```bash
adb install /tmp/termux-boot.apk
```

Expected: `Success`

**Step 6: Grant SMS permission to Termux:API**

```bash
adb shell pm grant com.termux.api android.permission.SEND_SMS
adb shell pm grant com.termux.api android.permission.READ_SMS
adb shell pm grant com.termux.api android.permission.RECEIVE_SMS
```

Expected: No output (silent success).

**GATE CHECK:** If Termux, Termux:API, and Termux:Boot are all installed → proceed to Task 2.
If any APK fails to install due to signing key mismatch → try alternative source. If no source works → abort and fall back to MacroDroid approach.

---

### Task 2: Validate SMS Sending

**Context:** Verify `termux-sms-send` actually dispatches SMS through the tablet's SIM.

**Files:** None (device-only)

**Step 1: Install termux-api package inside Termux**

```bash
adb shell "run-as com.termux /data/data/com.termux/files/usr/bin/bash -c 'pkg install termux-api -y'" 2>/dev/null
```

If the `run-as` approach doesn't work, open Termux on the tablet screen and type:
```bash
pkg install termux-api -y
```

**Step 2: Send a test SMS to Jake's phone**

From inside Termux on the tablet:
```bash
termux-sms-send -n +17348960518 "Test SMS from Samsung tablet gateway"
```

Expected: Jake receives the SMS from (734) 808-1176 within a few seconds.

**Step 3: Verify from ADB**

```bash
adb shell "run-as com.termux /data/data/com.termux/files/usr/bin/bash -c 'termux-sms-send -n +17348960518 \"ADB test from Samsung\"'"
```

Expected: SMS received by Jake.

**GATE CHECK:** If SMS is received → proceed to Task 3.
If `termux-sms-send` fails or SMS not received → check permissions, check SIM, check Termux:API version compatibility. If unsolvable → abort and fall back to MacroDroid.

---

### Task 3: Validate Python + HTTP Server

**Context:** We need Python running inside Termux to host the Flask gateway. If `pip install flask` fails (common on legacy Termux due to dead repos or OpenSSL issues), we fall back to Python's built-in `http.server`.

**Files:** None (device-only, but we'll create the gateway script)

**Step 1: Install Python in Termux**

Open Termux on the tablet:
```bash
pkg install python -y
python --version
```

Expected: Python 3.x installed. Note the version.

**Step 2: Try installing Flask**

```bash
pip install flask
```

Expected: Either succeeds, or fails with OpenSSL/wheel errors.

If flask installs → use Flask (Option A below).
If flask fails → use stdlib (Option B below).

**Step 3: Create the gateway script**

```bash
mkdir -p ~/sms-gateway
```

**Option A — Flask version** (`~/sms-gateway/gateway.py`):

```python
from flask import Flask, request, jsonify
import subprocess
import time
import json
import logging

logging.basicConfig(
    filename='/data/data/com.termux/files/home/sms-gateway/gateway.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

app = Flask(__name__)
start_time = time.time()
sms_count = 0

@app.route('/send-sms', methods=['POST'])
def send_sms():
    global sms_count
    data = request.json
    phone = data.get('phone', '')
    message = data.get('message', '')
    if not phone or not message:
        return jsonify({"success": False, "error": "missing phone or message"}), 400
    try:
        result = subprocess.run(
            ['termux-sms-send', '-n', phone, message],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            sms_count += 1
            logging.info(f"SMS sent to ...{phone[-4:]}")
            return jsonify({"success": True})
        else:
            logging.error(f"SMS failed to ...{phone[-4:]}: {result.stderr}")
            return jsonify({"success": False, "error": result.stderr.strip()})
    except subprocess.TimeoutExpired:
        logging.error(f"SMS timeout to ...{phone[-4:]}")
        return jsonify({"success": False, "error": "timeout"})
    except Exception as e:
        logging.error(f"SMS error to ...{phone[-4:]}: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/health')
def health():
    battery = {}
    try:
        bp = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=5)
        battery = json.loads(bp.stdout) if bp.returncode == 0 else {}
    except Exception:
        pass
    return jsonify({
        "status": "ok",
        "uptime_seconds": int(time.time() - start_time),
        "sms_sent_count": sms_count,
        "battery": battery
    })

if __name__ == '__main__':
    logging.info("Gateway starting on port 8686")
    app.run(host='0.0.0.0', port=8686)
```

**Option B — stdlib fallback** (`~/sms-gateway/gateway.py`):

```python
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess
import json
import time
import logging

logging.basicConfig(
    filename='/data/data/com.termux/files/home/sms-gateway/gateway.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

start_time = time.time()
sms_count = 0

class GatewayHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global sms_count
        if self.path != '/send-sms':
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        phone = body.get('phone', '')
        message = body.get('message', '')
        if not phone or not message:
            self._respond(400, {"success": False, "error": "missing phone or message"})
            return
        try:
            result = subprocess.run(
                ['termux-sms-send', '-n', phone, message],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                sms_count += 1
                logging.info(f"SMS sent to ...{phone[-4:]}")
                self._respond(200, {"success": True})
            else:
                logging.error(f"SMS failed to ...{phone[-4:]}: {result.stderr}")
                self._respond(200, {"success": False, "error": result.stderr.strip()})
        except subprocess.TimeoutExpired:
            logging.error(f"SMS timeout to ...{phone[-4:]}")
            self._respond(200, {"success": False, "error": "timeout"})
        except Exception as e:
            logging.error(f"SMS error to ...{phone[-4:]}: {e}")
            self._respond(200, {"success": False, "error": str(e)})

    def do_GET(self):
        if self.path != '/health':
            self.send_response(404)
            self.end_headers()
            return
        battery = {}
        try:
            bp = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=5)
            battery = json.loads(bp.stdout) if bp.returncode == 0 else {}
        except Exception:
            pass
        self._respond(200, {
            "status": "ok",
            "uptime_seconds": int(time.time() - start_time),
            "sms_sent_count": sms_count,
            "battery": battery
        })

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # Suppress default stderr logging

if __name__ == '__main__':
    logging.info("Gateway starting on port 8686")
    HTTPServer(('0.0.0.0', 8686), GatewayHandler).serve_forever()
```

**Step 4: Transfer the script to the tablet**

```bash
adb push ~/rrg-server/docs/plans/gateway.py /sdcard/gateway.py
adb shell "run-as com.termux cp /sdcard/gateway.py /data/data/com.termux/files/home/sms-gateway/gateway.py"
```

Or type/paste it directly in Termux if the `run-as` copy doesn't work.

**Step 5: Start the gateway and test from rrg-server**

In Termux on the tablet:
```bash
cd ~/sms-gateway && python gateway.py &
```

Find the tablet's current WiFi IP:
```bash
adb shell ip addr show wlan0 | grep "inet "
```

From rrg-server (SSH in first: `ssh andrea@rrg-server`):
```bash
curl -X POST http://<tablet-ip>:8686/send-sms \
  -H 'Content-Type: application/json' \
  -d '{"phone": "+17348960518", "message": "Test from rrg-server via Samsung gateway"}'
```

Expected: `{"success": true}` and Jake receives the SMS.

```bash
curl http://<tablet-ip>:8686/health
```

Expected: `{"status": "ok", "uptime_seconds": ..., "sms_sent_count": 1, "battery": {...}}`

**GATE CHECK:** If SMS sends successfully from rrg-server → proceed to Phase 2.
If connection refused or SMS fails → debug networking/Termux. If unsolvable → abort.

---

## Phase 2: Device Hardening

---

### Task 4: Fix Timezone and Display Settings

**Files:** None (ADB commands)

**Step 1: Fix timezone from Europe/London to America/Detroit**

```bash
adb shell settings put global auto_time_zone 0
adb shell setprop persist.sys.timezone America/Detroit
```

Expected: No output.

**Step 2: Verify timezone**

```bash
adb shell date
```

Expected: Shows Eastern Time.

**Step 3: Enable Stay Awake while charging**

```bash
adb shell settings put global stay_on_while_plugged_in 3
```

(Value 3 = stay awake on USB + AC + wireless charging)

**Step 4: Set screen timeout to maximum**

```bash
adb shell settings put system screen_off_timeout 2147483647
```

**Step 5: Commit — no code changes, just documenting progress**

No commit needed for device-only changes.

---

### Task 5: Disable Doze, Samsung Battery Management, and WiFi Quirks

**Files:** None (ADB commands)

**Step 1: Disable Doze mode**

```bash
adb shell dumpsys deviceidle disable
```

Expected: `Disabled`

Note: This does NOT persist across reboots. The boot script (Task 7) will re-apply it.

**Step 2: Exempt Termux from battery optimization**

```bash
adb shell cmd appops set com.termux RUN_IN_BACKGROUND allow 2>/dev/null
adb shell cmd appops set com.termux.api RUN_IN_BACKGROUND allow 2>/dev/null
adb shell cmd appops set com.termux.boot RUN_IN_BACKGROUND allow 2>/dev/null
```

Note: On Android 6, `cmd appops` may not support `RUN_IN_BACKGROUND`. If it errors, do this manually through tablet Settings → Battery → Battery Usage → Termux → toggle off "Restrict background data/battery".

**Step 3: Disable mobile data (SIM keeps SMS without data)**

```bash
adb shell svc data disable
```

Expected: Mobile data turns off. SMS still works over cellular radio.

**Step 4: Disable Smart Network Switch**

This must be done manually on the tablet:
- Settings → WiFi → More → Smart Network Switch → OFF

If the option doesn't exist on this firmware, skip it.

**Step 5: Keep WiFi on during sleep**

```bash
adb shell settings put global wifi_sleep_policy 2
```

(Value 2 = Never turn off WiFi during sleep)

---

### Task 6: Set Static IP on Tablet

**Context:** Must be set on-device (not just DHCP reservation) to survive DHCP lease failures. Choose an IP outside your router's DHCP range.

**Files:** None (manual device config)

**Step 1: Determine your subnet**

```bash
adb shell ip addr show wlan0 | grep "inet "
adb shell ip route | grep default
```

Note the current IP (e.g., `192.168.1.x`) and gateway (e.g., `192.168.1.1`).

**Step 2: Set static IP on the tablet**

This must be done in the Android WiFi settings UI:
- Settings → WiFi → long-press your network → Modify Network → Show Advanced Options
- IP Settings → Static
- IP Address: `192.168.1.250` (or another unused IP outside DHCP range)
- Gateway: your router IP (e.g., `192.168.1.1`)
- DNS 1: `8.8.8.8`
- DNS 2: `8.8.4.4`
- Network prefix length: `24`

**Step 3: Verify from rrg-server**

```bash
# From rrg-server:
ping -c 3 192.168.1.250
curl http://192.168.1.250:8686/health
```

Expected: Ping succeeds, health endpoint responds.

**Step 4: Set up ADB over WiFi for remote management**

While USB is still connected:
```bash
adb tcpip 5555
```

Then from rrg-server:
```bash
adb connect 192.168.1.250:5555
adb devices
```

Expected: `192.168.1.250:5555 device`

Now you can manage the tablet remotely from rrg-server without USB.

---

### Task 7: Set Up Auto-Start Boot Script

**Context:** Termux:Boot runs scripts in `~/.termux/boot/` on device boot. The script must also re-disable Doze (which resets on reboot).

**Files:** `~/.termux/boot/start-gateway.sh` (on the tablet)

**Step 1: Create the boot directory and script**

In Termux on the tablet:
```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-gateway.sh << 'SCRIPT'
#!/data/data/com.termux/files/usr/bin/bash

# Re-disable Doze (resets on reboot)
dumpsys deviceidle disable 2>/dev/null

# Log rotation: rename if > 10MB
LOG=~/sms-gateway/gateway.log
if [ -f "$LOG" ] && [ $(stat -c%s "$LOG" 2>/dev/null || echo 0) -gt 10485760 ]; then
    mv "$LOG" "$LOG.old"
fi

# Start the SMS gateway
cd ~/sms-gateway
python gateway.py >> ~/sms-gateway/gateway.log 2>&1 &
SCRIPT
chmod +x ~/.termux/boot/start-gateway.sh
```

**Step 2: Open Termux:Boot once to register it**

```bash
adb shell am start -n com.termux.boot/.BootActivity
```

Termux:Boot must be opened at least once after install to register as a boot receiver.

**Step 3: Test by rebooting**

```bash
adb reboot
```

Wait 60-90 seconds for the tablet to boot and Termux:Boot to fire.

**Step 4: Verify gateway auto-started**

From rrg-server:
```bash
curl http://192.168.1.250:8686/health
```

Expected: `{"status": "ok", ...}` — gateway is running.

If no response, connect via ADB over WiFi to debug:
```bash
adb connect 192.168.1.250:5555
adb shell "run-as com.termux cat /data/data/com.termux/files/home/sms-gateway/gateway.log"
```

---

### Task 8: Overnight Soak Test

**Context:** Leave the tablet running for 24 hours to verify it survives Doze/screen-off/WiFi drops.

**Files:** None

**Step 1: Set up a monitoring cron on rrg-server**

SSH into rrg-server:
```bash
ssh andrea@rrg-server
```

Create a temporary monitoring script:
```bash
cat > /tmp/check-samsung-gateway.sh << 'EOF'
#!/bin/bash
RESULT=$(curl -sf --max-time 5 http://192.168.1.250:8686/health)
if [ $? -ne 0 ]; then
    echo "$(date): Samsung gateway UNREACHABLE" >> /tmp/samsung-gateway-monitor.log
else
    echo "$(date): OK - $RESULT" >> /tmp/samsung-gateway-monitor.log
fi
EOF
chmod +x /tmp/check-samsung-gateway.sh
```

Add a temporary cron (every 5 minutes):
```bash
(crontab -l 2>/dev/null; echo "*/5 * * * * /tmp/check-samsung-gateway.sh") | crontab -
```

**Step 2: Wait 24 hours**

**Step 3: Check results**

```bash
ssh andrea@rrg-server "cat /tmp/samsung-gateway-monitor.log | grep -c UNREACHABLE"
ssh andrea@rrg-server "cat /tmp/samsung-gateway-monitor.log | wc -l"
```

Expected: 0 unreachable entries out of ~288 checks.

**Step 4: Send a real SMS after 24 hours**

```bash
ssh andrea@rrg-server "curl -sf -X POST http://192.168.1.250:8686/send-sms -H 'Content-Type: application/json' -d '{\"phone\": \"+17348960518\", \"message\": \"24h soak test passed\"}'"
```

Expected: SMS received.

**Step 5: Clean up temp monitoring cron**

```bash
ssh andrea@rrg-server "crontab -l | grep -v check-samsung-gateway | crontab -"
ssh andrea@rrg-server "rm /tmp/check-samsung-gateway.sh /tmp/samsung-gateway-monitor.log"
```

**GATE CHECK:** If >=95% uptime and SMS works after 24h → proceed to Phase 3.
If frequent drops → investigate WiFi/Doze settings. If unsolvable → reconsider device choice.

---

## Phase 3: Windmill Changes

---

### Task 9: Create Windmill Variable for Residential Gateway

**Context:** Add `f/switchboard/sms_gateway_url_residential` pointing to the Samsung tablet's static local IP.

**Files:** Windmill UI (no local file change)

**Step 1: Create the variable in Windmill**

From jake-macbook, use the Windmill API:

```bash
curl -X POST "http://100.97.86.99:8000/api/w/rrg/variables/create" \
  -H "Authorization: Bearer $(cat ~/.secrets/jake-system.json | python3 -c 'import sys,json; print(json.load(sys.stdin)["windmill"]["api_token"])')" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "f/switchboard/sms_gateway_url_residential",
    "value": "http://192.168.1.250:8686/send-sms",
    "is_secret": false,
    "description": "SMS gateway URL for residential leads (Samsung Tab E, local WiFi)"
  }'
```

Expected: `"f/switchboard/sms_gateway_url_residential"` (path returned)

**Step 2: Verify the variable**

```bash
curl -s "http://100.97.86.99:8000/api/w/rrg/variables/get/f/switchboard/sms_gateway_url_residential" \
  -H "Authorization: Bearer $(cat ~/.secrets/jake-system.json | python3 -c 'import sys,json; print(json.load(sys.stdin)["windmill"]["api_token"])')" | python3 -c 'import sys,json; print(json.load(sys.stdin)["value"])'
```

Expected: `http://192.168.1.250:8686/send-sms`

---

### Task 10: Update Lead Intake Post-Approval SMS Routing

**Context:** Modify `lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` to select gateway per-draft based on `source_type`.

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py:177`

**Step 1: Replace the single gateway URL with dual-gateway routing**

Change line 177 from:
```python
        SMS_GATEWAY_URL = wmill.get_variable("f/switchboard/sms_gateway_url")
```

To:
```python
        SMS_GATEWAY_COMMERCIAL = wmill.get_variable("f/switchboard/sms_gateway_url")
        SMS_GATEWAY_RESIDENTIAL = wmill.get_variable("f/switchboard/sms_gateway_url_residential")
        RESIDENTIAL_SOURCES = {"realtor_com", "seller_hub", "social_connect", "upnest"}
```

**Step 2: Update the SMS loop to select gateway per draft**

Inside the `for draft in drafts:` loop (starting at line 180), add gateway selection after `phone = draft.get("phone", "")` (line 182):

Insert after line 182:
```python
            source_type = draft.get("source_type", "")
            gateway_url = SMS_GATEWAY_RESIDENTIAL if source_type in RESIDENTIAL_SOURCES else SMS_GATEWAY_COMMERCIAL
```

**Step 3: Replace `SMS_GATEWAY_URL` with `gateway_url` in the requests.post call**

Change line 197-199 from:
```python
                sms_resp = requests.post(
                    SMS_GATEWAY_URL,
                    json={"phone": phone_e164, "message": sms_body},
```

To:
```python
                sms_resp = requests.post(
                    gateway_url,
                    json={"phone": phone_e164, "message": sms_body},
```

**Step 4: Sync to Windmill**

```bash
cd ~/rrg-server && wmill sync push --skip-variables --skip-secrets --skip-resources
```

Expected: Script pushes successfully.

**Step 5: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/post_approval_\(crm_+_sms\).inline_script.py
git commit -m "feat: route residential lead SMS through Samsung tablet gateway

Add per-draft gateway selection based on source_type. Commercial sources
(crexi, loopnet, bizbuysell) use Pixel 9a. Residential sources (realtor_com,
seller_hub, social_connect, upnest) use Samsung tablet.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 11: Update Lead Conversation Post-Approval SMS Routing

**Context:** Same change as Task 10, but for `lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py`.

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py:175`

**Step 1: Replace the single gateway URL with dual-gateway routing**

Change line 175 from:
```python
        SMS_GATEWAY_URL = wmill.get_variable("f/switchboard/sms_gateway_url")
```

To:
```python
        SMS_GATEWAY_COMMERCIAL = wmill.get_variable("f/switchboard/sms_gateway_url")
        SMS_GATEWAY_RESIDENTIAL = wmill.get_variable("f/switchboard/sms_gateway_url_residential")
        RESIDENTIAL_SOURCES = {"realtor_com", "seller_hub", "social_connect", "upnest"}
```

**Step 2: Update the SMS loop to select gateway per draft**

Inside the `for draft in drafts:` loop (starting at line 178), add after `phone = draft.get("phone", "")` (line 180):

```python
            source_type = draft.get("source_type", "")
            gateway_url = SMS_GATEWAY_RESIDENTIAL if source_type in RESIDENTIAL_SOURCES else SMS_GATEWAY_COMMERCIAL
```

**Step 3: Replace `SMS_GATEWAY_URL` with `gateway_url` in the requests.post call**

Change line 195-197 from:
```python
                sms_resp = requests.post(
                    SMS_GATEWAY_URL,
                    json={"phone": phone_e164, "message": sms_body},
```

To:
```python
                sms_resp = requests.post(
                    gateway_url,
                    json={"phone": phone_e164, "message": sms_body},
```

**Step 4: Sync to Windmill**

```bash
cd ~/rrg-server && wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 5: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/post_approval_\(crm_+_sms\).inline_script.py
git commit -m "feat: route residential conversation SMS through Samsung tablet gateway

Same dual-gateway pattern as lead_intake post-approval module.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 12: Create SMS Gateway Health Check Script

**Context:** New Windmill script that checks both SMS gateways every 15 minutes. Uses cross-alerting: if one gateway is down, alert via the other.

**Files:**
- Create: `windmill/f/switchboard/check_sms_gateway_health.py`

**Step 1: Create the health check script**

Create `windmill/f/switchboard/check_sms_gateway_health.py`:

```python
# SMS Gateway Health Check
# Path: f/switchboard/check_sms_gateway_health
#
# Checks both SMS gateways (Pixel 9a commercial + Samsung tablet residential).
# Cross-alerting: if one is down, sends alert via the other.
#
# Schedule: Every 15 minutes

#extra_requirements:
#requests

import wmill
import requests


def main():
    commercial_url = wmill.get_variable("f/switchboard/sms_gateway_url")
    residential_url = wmill.get_variable("f/switchboard/sms_gateway_url_residential")

    # Derive health URLs from send-sms URLs
    commercial_health = commercial_url.replace("/send-sms", "/health")
    residential_health = residential_url.replace("/send-sms", "/health")

    results = {}

    # Check commercial gateway (Pixel 9a)
    try:
        resp = requests.get(commercial_health, timeout=10)
        resp.raise_for_status()
        results["commercial"] = {"status": "healthy", "data": resp.json()}
    except Exception as e:
        results["commercial"] = {"status": "down", "error": str(e)}

    # Check residential gateway (Samsung tablet)
    try:
        resp = requests.get(residential_health, timeout=10)
        resp.raise_for_status()
        results["residential"] = {"status": "healthy", "data": resp.json()}
    except Exception as e:
        results["residential"] = {"status": "down", "error": str(e)}

    # Cross-alerting
    if results["commercial"]["status"] == "down":
        # Alert via residential gateway
        try:
            requests.post(
                residential_url,
                json={
                    "phone": "+17348960518",
                    "message": f"[RRG Alert] Commercial SMS gateway (Pixel 9a) is DOWN: {results['commercial']['error'][:80]}"
                },
                timeout=15
            )
            results["commercial"]["alert_sent_via"] = "residential"
        except Exception:
            results["commercial"]["alert_sent_via"] = "failed"

    if results["residential"]["status"] == "down":
        # Alert via commercial gateway
        try:
            requests.post(
                commercial_url,
                json={
                    "phone": "+17348960518",
                    "message": f"[RRG Alert] Residential SMS gateway (Samsung tablet) is DOWN: {results['residential']['error'][:80]}"
                },
                timeout=15
            )
            results["residential"]["alert_sent_via"] = "commercial"
        except Exception:
            results["residential"]["alert_sent_via"] = "failed"

    return results
```

**Step 2: Sync to Windmill**

```bash
cd ~/rrg-server && wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 3: Create the schedule in Windmill**

Via Windmill UI or API — create schedule `f/switchboard/sms_gateway_health_check`:
- Script: `f/switchboard/check_sms_gateway_health`
- Cron: `0 */15 * * * *` (every 15 minutes)

**Step 4: Test manually**

Run the script once from Windmill UI. Expected output:
```json
{
  "commercial": {"status": "healthy", "data": {"status": "ok", ...}},
  "residential": {"status": "healthy", "data": {"status": "ok", ...}}
}
```

**Step 5: Commit**

```bash
git add windmill/f/switchboard/check_sms_gateway_health.py
git commit -m "feat: add SMS gateway health check with cross-alerting

Checks both Pixel 9a (commercial) and Samsung tablet (residential)
gateways every 15 minutes. If one is down, alerts Jake via the other.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Phase 4: Documentation

---

### Task 13: Update Network and Architecture Docs

**Files:**
- Modify: `.claude/rules/network.md`
- Modify: `docs/CURRENT_STATE.md:244-253`
- Modify: `CLAUDE.md` (SMS gateway section)

**Step 1: Update network.md**

Add Samsung tablet to the machine table in `.claude/rules/network.md`:

Add row to the Tailscale Machines table (even though it's not on Tailscale, for completeness):
```
| samsung-tab-e | 192.168.1.250 (local WiFi) | — | SMS gateway - residential (Termux + Flask, local WiFi only) |
```

Add to Key Ports:
```
- SMS Gateway (residential): 8686 (samsung-tab-e, local WiFi, Termux Flask)
```

**Step 2: Update CURRENT_STATE.md variables table**

Add row after the `sms_gateway_url` entry:
```
| `f/switchboard/sms_gateway_url_residential` | SMS gateway URL (Samsung Tab E, residential leads) | No | `lead_intake/post_approval`, `lead_conversation/post_approval`, `check_sms_gateway_health` |
```

**Step 3: Update CLAUDE.md**

In the Windmill Resources & Variables section, add `sms_gateway_url_residential` to the Variables list.

In the "Four machines on Tailscale" section, add a note about the Samsung tablet (local WiFi, not Tailscale).

**Step 4: Update MEMORY.md**

Add a Samsung Tablet section to `/Users/jacobphillips/.claude/projects/-Users-jacobphillips-rrg-server/memory/MEMORY.md`:

```markdown
## Samsung Tab E SMS Gateway (Residential)
- Device: Samsung Galaxy Tab E 8.0 (SM-T377A), Android 6.0.1
- Phone: (734) 808-1176, Local WiFi IP: 192.168.1.250, port 8686
- Role: SMS gateway for residential leads ONLY (Realtor.com, Seller Hub, Social Connect, UpNest)
- NOT on Tailscale (Android 6 too old — requires Android 8+)
- Reachable from rrg-server via local WiFi only
- ADB over WiFi: `adb connect 192.168.1.250:5555` (from rrg-server)
- Gateway stack: Termux (legacy Android 5/6 build) + Flask (or stdlib fallback)
- Auto-start: ~/.termux/boot/start-gateway.sh via Termux:Boot
- Hardening: Doze disabled (re-applied on boot), mobile data off, WiFi always on, static IP
- Windmill var: f/switchboard/sms_gateway_url_residential = http://192.168.1.250:8686/send-sms
- Health check: f/switchboard/check_sms_gateway_health (every 15 min, cross-alerts with Pixel 9a)
```

Update the Pixel 9a section to clarify it's now commercial-only.

**Step 5: Commit all doc changes**

```bash
git add .claude/rules/network.md docs/CURRENT_STATE.md CLAUDE.md
git commit -m "docs: add Samsung tablet residential SMS gateway to all docs

Add samsung-tab-e to network table, add sms_gateway_url_residential
variable, update architecture notes for dual-gateway setup.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 14: End-to-End Verification

**Context:** Verify the full pipeline works: Windmill post-approval module selects the correct gateway based on source type.

**Files:** None (testing only)

**Step 1: Verify both gateways are healthy**

```bash
curl -sf http://192.168.1.250:8686/health && echo "Samsung: OK"
curl -sf http://100.125.176.16:8686/health && echo "Pixel: OK"
```

**Step 2: Test gateway routing logic manually**

From rrg-server, simulate what the post-approval module does:

```bash
# Commercial lead (should go to Pixel 9a):
curl -sf -X POST http://100.125.176.16:8686/send-sms \
  -H 'Content-Type: application/json' \
  -d '{"phone": "+17348960518", "message": "E2E test: commercial via Pixel"}'

# Residential lead (should go to Samsung tablet):
curl -sf -X POST http://192.168.1.250:8686/send-sms \
  -H 'Content-Type: application/json' \
  -d '{"phone": "+17348960518", "message": "E2E test: residential via Samsung"}'
```

Expected: Two SMS received — one from (734) 932-0111 (Pixel), one from (734) 808-1176 (Samsung).

**Step 3: Verify health check runs**

Trigger `f/switchboard/check_sms_gateway_health` manually in Windmill UI. Expected: both gateways report healthy.

**Step 4: Remove temporary monitoring cron from rrg-server (if still present from Task 8)**

```bash
ssh andrea@rrg-server "crontab -l | grep -v check-samsung-gateway | crontab -"
```
