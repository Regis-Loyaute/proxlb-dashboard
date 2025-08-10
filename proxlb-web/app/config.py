import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass(frozen=True)
class Settings:
    PVE_HOSTS: list[str]
    PVE_USER: str
    PVE_TOKEN_ID: str
    PVE_TOKEN_SECRET: str
    VERIFY_SSL: bool
    FLASK_SECRET: str

def load_settings() -> Settings:
    load_dotenv()
    hosts = [h.strip() for h in os.getenv("PVE_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        raise RuntimeError("PVE_HOSTS is empty. Set it in your .env (comma-separated).")
    return Settings(
        PVE_HOSTS=hosts,
        PVE_USER=os.getenv("PVE_USER", "root@pam"),
        PVE_TOKEN_ID=os.getenv("PVE_TOKEN_ID", "proxlb"),
        PVE_TOKEN_SECRET=os.getenv("PVE_TOKEN_SECRET", ""),
        VERIFY_SSL=os.getenv("VERIFY_SSL", "false").lower() == "true",
        FLASK_SECRET=os.getenv("FLASK_SECRET", "change-me"),
    )

def configure_ssl_warnings(verify_ssl: bool) -> None:
    if not verify_ssl:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
