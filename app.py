#!/usr/bin/env python3
import os, re, time
import requests
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from dotenv import load_dotenv

# ---- Load config from .env ----
load_dotenv()
PVE_HOSTS = [h.strip() for h in os.getenv("PVE_HOSTS", "").split(",") if h.strip()]
PVE_USER = os.getenv("PVE_USER", "root@pam")
PVE_TOKEN_ID = os.getenv("PVE_TOKEN_ID", "proxlb")
PVE_TOKEN_SECRET = os.getenv("PVE_TOKEN_SECRET", "")
VERIFY_SSL = os.getenv("VERIFY_SSL", "false").lower() == "true"

# Mute SSL warnings if VERIFY_SSL is false
if not VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")

# --------- Proxmox API helpers ---------
def _headers():
    return {"Authorization": f"PVEAPIToken={PVE_USER}!{PVE_TOKEN_ID}={PVE_TOKEN_SECRET}"}

def _call(host, path, method="GET", data=None, timeout=10):
    url = f"https://{host}:8006/api2/json/{path}"
    if method == "GET":
        r = requests.get(url, headers=_headers(), verify=VERIFY_SSL, timeout=timeout)
    else:
        # Proxmox expects form-encoded for most endpoints
        r = requests.post(url, headers=_headers(), data=data, verify=VERIFY_SSL, timeout=max(timeout, 30))
    r.raise_for_status()
    return r.json()

def any_host():
    last_err = None
    for h in PVE_HOSTS:
        try:
            _call(h, "version", timeout=3)
            return h
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"No reachable PVE hosts: {last_err}")

def api(path, method="GET", data=None, timeout=10):
    """Cluster-safe call: always use a reachable API host, keep node names in the path only."""
    host = any_host()
    return _call(host, path, method, data, timeout)

# --------- Data providers ----------
def get_nodes():
    resp = api("nodes")
    nodes = resp.get("data", []) if resp else []
    for n in nodes:
        n["cpu_pct"] = round(float(n.get("cpu", 0)) * 100, 1)
        maxmem = float(n.get("maxmem", 0)) or 1.0
        n["mem_pct"] = round(float(n.get("mem", 0)) / maxmem * 100, 1)
    return nodes

def get_vms():
    resp = api("cluster/resources?type=vm")
    vms = resp.get("data", []) if resp else []
    vms.sort(key=lambda x: (x.get("node",""), int(x.get("vmid", 0))))
    return vms

def storage_shared_map(node):
    """Return {storage_id: shared_bool} for a node."""
    try:
        resp = api(f"nodes/{node}/storage")
        res = {}
        for s in resp.get("data", []):
            res[s["storage"]] = bool(s.get("shared", 0))
        return res
    except Exception:
        return {}

def vm_needs_with_local_disks(node, vmid):
    """Check VM disks; if any on non-shared storage, return True."""
    try:
        cfg = api(f"nodes/{node}/qemu/{vmid}/config").get("data", {})
        shared_by_storage = storage_shared_map(node)
        for k, v in cfg.items():
            if any(k.startswith(pfx) for pfx in ("scsi", "sata", "virtio", "ide")) and isinstance(v, str):
                storage_id = v.split(":", 1)[0]
                if not shared_by_storage.get(storage_id, False):
                    return True
        return False
    except Exception:
        # be safe: allow with-local-disks
        return True

def parse_percent_from_logs(lines):
    """Extract highest % seen in task log lines."""
    pct = 0
    for entry in lines:
        t = entry.get("t", "")
        m = re.search(r"(\d+)%", t)
        if m:
            pct = max(pct, int(m.group(1)))
    return pct

# --------- Pages ----------
@app.route("/")
def index():
    return render_template("dashboard.html", nodes=get_nodes(), vms=get_vms())

# --------- API: start migrate (returns upid) ----------
@app.route("/api/migrate", methods=["POST"])
def api_migrate():
    data = request.get_json(force=True)
    node = data["node"]
    vmid = int(data["vmid"])
    target = data.get("target")  # optional

    # choose target if not provided
    candidates = [n["node"] for n in get_nodes() if n["node"] != node]
    if not candidates:
        return jsonify({"error": "no_target"}), 400
    target = target or candidates[0]

    # live/offline based on current status
    status = api(f"nodes/{node}/qemu/{vmid}/status/current").get("data", {}).get("status", "stopped")
    payload = {"target": target, "online": 1 if status == "running" else 0}

    # local disks?
    if vm_needs_with_local_disks(node, vmid):
        payload["with-local-disks"] = 1

    try:
        resp = api(f"nodes/{node}/qemu/{vmid}/migrate", method="POST", data=payload)
        upid = resp.get("data")
        return jsonify({"upid": upid, "node": node, "target": target, "online": payload["online"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --------- API: poll task status ----------
@app.route("/api/task_status")
def api_task_status():
    node = request.args.get("node")
    upid = request.args.get("upid")
    if not node or not upid:
        return jsonify({"error": "missing_params"}), 400
    try:
        st = api(f"nodes/{node}/tasks/{upid}/status").get("data", {})
        # progress from logs (best effort)
        logs = api(f"nodes/{node}/tasks/{upid}/log").get("data", [])
        percent = parse_percent_from_logs(logs)
        return jsonify({"status": st.get("status"), "exitstatus": st.get("exitstatus"), "percent": percent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --------- QEMU actions (start/stop/reboot) ----------
@app.route("/action/<node>/<int:vmid>/<act>", methods=["POST"])
def action(node, vmid, act):
    try:
        api(f"nodes/{node}/qemu/{vmid}/status/{act}", method="POST")
        flash(f"{act} sent to VM {vmid} on {node}")
    except Exception as e:
        flash(f"Action failed: {e}")
    return redirect(url_for("index"))

# --------- Main ---------
if __name__ == "__main__":
    # Dev server (use systemd/gunicorn in prod)
    app.run(host="0.0.0.0", port=5000, debug=True)
