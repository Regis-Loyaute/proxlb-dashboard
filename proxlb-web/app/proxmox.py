from __future__ import annotations
import re
from typing import Any, Dict, List
import requests

class ProxmoxClient:
    def __init__(self, hosts: list[str], user: str, token_id: str, token_secret: str, verify_ssl: bool) -> None:
        self.hosts = hosts
        self.user = user
        self.token_id = token_id
        self.token_secret = token_secret
        self.verify_ssl = verify_ssl

    # ---- internal helpers ----
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"PVEAPIToken={self.user}!{self.token_id}={self.token_secret}"}

    def _call(self, host: str, path: str, method: str = "GET", data: Dict[str, Any] | None = None, timeout: int = 10) -> Dict[str, Any]:
        url = f"https://{host}:8006/api2/json/{path}"
        if method == "GET":
            r = requests.get(url, headers=self._headers(), verify=self.verify_ssl, timeout=timeout)
        else:
            r = requests.post(url, headers=self._headers(), data=data, verify=self.verify_ssl, timeout=max(timeout, 30))
        r.raise_for_status()
        return r.json()

    def _any_host(self) -> str:
        last_err: Exception | None = None
        for h in self.hosts:
            try:
                self._call(h, "version", timeout=3)
                return h
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        raise RuntimeError(f"No reachable PVE hosts: {last_err}")

    def api(self, path: str, method: str = "GET", data: Dict[str, Any] | None = None, timeout: int = 10) -> Dict[str, Any]:
        host = self._any_host()
        return self._call(host, path, method, data, timeout)

    # ---- convenience wrappers used by routes/services ----
    def get_nodes(self) -> List[Dict[str, Any]]:
        resp = self.api("nodes").get("data", [])
        for n in resp:
            n["cpu_pct"] = round(float(n.get("cpu", 0)) * 100, 1)
            maxmem = float(n.get("maxmem", 0)) or 1.0
            n["mem_pct"] = round(float(n.get("mem", 0)) / maxmem * 100, 1)
        return resp

    def get_vms(self) -> List[Dict[str, Any]]:
        vms = self.api("cluster/resources?type=vm").get("data", [])
        vms.sort(key=lambda x: (x.get("node", ""), int(x.get("vmid", 0))))
        return vms

    def storage_shared_map(self, node: str) -> Dict[str, bool]:
        res: Dict[str, bool] = {}
        try:
            for s in self.api(f"nodes/{node}/storage").get("data", []):
                res[s["storage"]] = bool(s.get("shared", 0))
        except Exception:  # noqa: BLE001
            pass
        return res

    def vm_has_local_disks(self, node: str, vmid: int) -> bool:
        try:
            cfg = self.api(f"nodes/{node}/qemu/{vmid}/config").get("data", {})
            shared = self.storage_shared_map(node)
            for k, v in cfg.items():
                if any(k.startswith(p) for p in ("scsi", "sata", "virtio", "ide")) and isinstance(v, str):
                    storage_id = v.split(":", 1)[0]
                    if not shared.get(storage_id, False):
                        return True
            return False
        except Exception:  # noqa: BLE001
            return True

    @staticmethod
    def parse_percent_from_logs(lines: List[Dict[str, Any]]) -> int:
        pct = 0
        for entry in lines or []:
            m = re.search(r"(\d{1,3})\s*%", entry.get("t", ""))
            if m:
                try:
                    pct = max(pct, min(100, int(m.group(1))))
                except ValueError:
                    pass
        return pct
