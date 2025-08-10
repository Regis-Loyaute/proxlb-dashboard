from __future__ import annotations
from flask import Blueprint, current_app, jsonify, request, flash, redirect, url_for
from ..proxmox import ProxmoxClient
from ..services.migration import start_migration

bp = Blueprint("api", __name__)

def _pve() -> ProxmoxClient:
    s = current_app.config["SETTINGS"]
    return ProxmoxClient(s.PVE_HOSTS, s.PVE_USER, s.PVE_TOKEN_ID, s.PVE_TOKEN_SECRET, s.VERIFY_SSL)

@bp.post("/migrate")
def api_migrate():
    data = request.get_json(force=True)
    node = data["node"]
    vmid = int(data["vmid"])
    target = data.get("target")
    try:
        res = start_migration(_pve(), node, vmid, target)
        if "error" in res:
            return jsonify(res), 400
        return jsonify(res)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500

@bp.get("/task_status")
def api_task_status():
    node = request.args.get("node")
    upid = request.args.get("upid")
    start = int(request.args.get("start", "0"))
    if not node or not upid:
        return jsonify({"error": "missing_params"}), 400

    pve = _pve()
    try:
        st = pve.api(f"nodes/{node}/tasks/{upid}/status").get("data", {})
        lines = pve.api(f"nodes/{node}/tasks/{upid}/log?start={start}").get("data", [])

        next_start = start
        if lines:
            next_start = max(l.get("n", start) for l in lines) + 1

        percent = pve.parse_percent_from_logs(lines)
        running = (st.get("status") == "running")
        exitstatus = st.get("exitstatus")

        if st.get("status") == "stopped" and (exitstatus or "").upper() == "OK":
            percent = max(percent, 100)

        return jsonify({
            "status": st.get("status"),
            "exitstatus": exitstatus,
            "percent": percent if percent else (None if running else 0),
            "next_start": next_start,
            "new_logs": [l.get("t","") for l in lines],
        })
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500

# Optional: simple action endpoints preserved via server post+redirect
@bp.post("/action/<node>/<int:vmid>/<act>")
def action(node, vmid, act):
    try:
        _pve().api(f"nodes/{node}/qemu/{vmid}/status/{act}", method="POST")
        flash(f"{act} sent to VM {vmid} on {node}")
    except Exception as e:  # noqa: BLE001
        flash(f"Action failed: {e}")
    return redirect(url_for("dashboard.index"))
