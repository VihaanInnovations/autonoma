import subprocess
import shutil
import os
from pathlib import Path

class ServiceManager:
    def __init__(self):
        self.service_name = "hybrid-reviewer"

    def is_installed(self) -> bool:
        """Check if service unit exists in user systemd dir"""
        systemd_dir = Path.home() / ".config" / "systemd" / "user"
        return (systemd_dir / f"{self.service_name}.service").exists()

    def status(self) -> str:
        """Get service status (active, inactive, failed, unknown)"""
        if not shutil.which("systemctl"):
            return "unknown"
        
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", self.service_name],
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        except Exception:
            return "error"

    def start(self):
        """Start the service"""
        if not shutil.which("systemctl"):
            raise RuntimeError("Systemd not found")
        subprocess.run(["systemctl", "--user", "start", self.service_name], check=True)

    def stop(self):
        """Stop the service"""
        if not shutil.which("systemctl"):
            raise RuntimeError("Systemd not found")
        subprocess.run(["systemctl", "--user", "stop", self.service_name], check=True)

    def restart(self):
        """Restart the service"""
        if not shutil.which("systemctl"):
            raise RuntimeError("Systemd not found")
        subprocess.run(["systemctl", "--user", "restart", self.service_name], check=True)
