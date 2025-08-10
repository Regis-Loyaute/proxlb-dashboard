from __future__ import annotations
from typing import Any, Dict, Optional
from ..proxmox import ProxmoxClient

def pick_target(pve: ProxmoxClient, exclude_node: str) -> Optional[str]:
    nodes = [n for n in pve.get_nodes() if n.get("node") != exclude_node and n.get("status") == "online"]
    if not nodes:
        return None
    nodes.sort(key=lambda n: (n.get("cpu_pct", 1000), n.get("mem_pct", 1000)))
    return nodes[0]["node"]

def start_migration(pve: ProxmoxClient, node: str, vmid: int, target: Optional[str]) -> Dict[str, Any]:
    target = target or pick_target(pve, exclude_node=node)
    if not target:
        return {"error": "no_target"}

    status = pve.api(f"nodes/{node}/qemu/{vmid}/status/current").get("data", {}).get("status", "stopped")
    payload: Dict[str, Any] = {"target": target, "online": 1 if status == "running" else 0}

    if pve.vm_has_local_disks(node, vmid):
        payload["with-local-disks"] = 1

    upid = pve.api(f"nodes/{node}/qemu/{vmid}/migrate", method="POST", data=payload).get("data")
    return {"upid": upid, "node": node, "target": target, "online": payload["online"]}
