from flask import Blueprint, current_app, render_template
from ..proxmox import ProxmoxClient

bp = Blueprint("dashboard", __name__)

@bp.route("/")
def index():
    s = current_app.config["SETTINGS"]
    pve = ProxmoxClient(s.PVE_HOSTS, s.PVE_USER, s.PVE_TOKEN_ID, s.PVE_TOKEN_SECRET, s.VERIFY_SSL)
    return render_template("dashboard.html", nodes=pve.get_nodes(), vms=pve.get_vms())
