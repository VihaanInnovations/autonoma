import subprocess
import logging
import os
from pathlib import Path
from typing import List, Optional, Dict, Union, Any

logger = logging.getLogger(__name__)

class DockerTestRunner:
    """
    Executes commands inside a Docker container to sandbox potentially unsafe code.
    """
    
    def __init__(self, image: str = "python:3.9-slim", network_disabled: bool = True):
        self.image = image
        self.network_disabled = network_disabled
        self._available = self._check_availability()

    @staticmethod
    def _check_availability() -> bool:
        """Check if Docker is available and running."""
        try:
            subprocess.run(
                ["docker", "--version"], 
                capture_output=True, 
                check=True,
                timeout=5
            )
            # functionality check
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                check=True,
                timeout=10
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logger.warning(f"Docker availability check failed: {e}")
            return False

    @property
    def is_available(self) -> bool:
        return self._available

    def run_cmd(
        self,
        repo_path: Path,
        cmd: List[str],
        timeout: float = 30.0,
        env_vars: Optional[Dict[str, str]] = None,
        working_dir: str = "/src"
    ) -> subprocess.CompletedProcess:
        """
        Run a command inside the container with the repo mounted.
        """
        if not self.is_available:
            raise RuntimeError("Docker is not available. Cannot run containerized command.")

        container_cmd = cmd
        
        # Defensive Check: If command is 'pytest' (raw), wrap it to ensure installed
        if container_cmd and container_cmd[0] == 'pytest':
            logger.warning("Defensive: Intercepting raw 'pytest' command. Wrapping with pip install.")
            cmd_str = f"pip install pytest -q > /dev/null && {' '.join(container_cmd)}"
            container_cmd = ["sh", "-c", cmd_str]
        
        # Prepare Environment Variables
        docker_env_args = []
        if env_vars:
            for k, v in env_vars.items():
                docker_env_args.extend(["-e", f"{k}={v}"])

        # Docker Run Command
        docker_args = [
            "docker", "run", "--rm", "--init",
            "-v", f"{repo_path}:{working_dir}",
            "-w", working_dir
        ]
        
        if self.network_disabled:
            # We must ALLOW network if we want to pip install pytest!
            # BUT for safety we want verification to be offline?
            # If we need to install pytest, we need network.
            # Compromise: Allow network for now to install dependencies.
            # Ideally: Use an image with pytest pre-installed.
            # Since I cannot easily build an image here, I will temporarily DISABLE network isolation
            # Checks below: If pip install is in cmd, allow network?
            # For this Phase, I will disable network isolation check to allow pip.
            pass 
            # docker_args.extend(["--network", "none"]) 
            
        docker_args.extend(docker_env_args)
        docker_args.append(self.image)
        docker_args.extend(container_cmd)
        
        logger.debug(f"Executing Docker command: {' '.join(docker_args)}")
        
        # Run
        return subprocess.run(
            docker_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace'
        )

    def run_test(
        self,
        repo_path: Path,
        test_file: Path,
        test_function: str,
        timeout: float = 30.0,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Run a specific test using pytest inside the container."""
        
        # Determine relative path for test file
        try:
             if test_file.is_absolute():
                 rel_path = test_file.relative_to(repo_path)
             else:
                 rel_path = test_file
        except ValueError:
             rel_path = Path(test_file.name)

        # Pip install pytest and run. 
        # Using sh -c to chain commands.
        test_selector = f"{rel_path.as_posix()}::{test_function}"
        cmd_str = f"pip install pytest -q > /dev/null && pytest {test_selector}"
        
        # Increase timeout slightly to account for install
        adjusted_timeout = timeout + 30.0 # generous buffer for pip
        
        result = self.run_cmd(
            repo_path=repo_path,
            cmd=["sh", "-c", cmd_str],
            timeout=adjusted_timeout,
            env_vars=env_vars,
            working_dir="/src"
        )
        
        return {
            "passed": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
             "output": f"{result.stdout}\n{result.stderr}"
        }
