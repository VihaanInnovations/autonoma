"""
Hardware Fingerprinting Module
Generates unique, stable machine identifiers for license binding.
"""
import platform
import subprocess
import uuid
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Cache machine ID to avoid regenerating on every call
_cached_machine_id: Optional[str] = None

def get_machine_id(force_refresh: bool = False) -> str:
    """
    Get machine fingerprint using multiple hardware identifiers.
    Creates a unique, stable identifier for the machine.
    
    Uses:
    - CPU ID/Serial
    - MAC Address (primary network interface)
    - Disk Serial Number
    - OS Information
    - Machine Name
    
    Returns a 32-character hex hash that uniquely identifies the machine.
    
    Args:
        force_refresh: If True, regenerate machine ID even if cached
    
    Returns:
        32-character hexadecimal machine ID
    """
    global _cached_machine_id
    
    if _cached_machine_id and not force_refresh:
        return _cached_machine_id
    
    components = []
    
    # 1. CPU ID/Processor Information
    try:
        if platform.system() == "Windows":
            try:
                # Try to get ProcessorId (most reliable)
                result = subprocess.check_output(
                    'wmic cpu get ProcessorId', 
                    shell=True,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                ).decode().strip()
                cpu_id = result.split('\n')[1].strip() if '\n' in result else "unknown"
                if not cpu_id or cpu_id == "":
                    # Fallback to processor name
                    result = subprocess.check_output(
                        'wmic cpu get Name',
                        shell=True,
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    ).decode().strip()
                    cpu_id = result.split('\n')[1].strip() if '\n' in result else platform.processor()
            except Exception as e:
                logger.debug(f"Failed to get Windows CPU ID: {e}")
                cpu_id = platform.processor() or "unknown"
        elif platform.system() == "Linux":
            try:
                # Try to get CPU serial from /proc/cpuinfo
                cpuinfo = subprocess.check_output(
                    ['cat', '/proc/cpuinfo'],
                    stderr=subprocess.DEVNULL,
                    timeout=5
                ).decode()
                if 'Serial' in cpuinfo:
                    cpu_id = cpuinfo.split('Serial')[1].split('\n')[0].strip()
                else:
                    # Use processor name
                    cpu_id = platform.processor() or "unknown"
            except Exception as e:
                logger.debug(f"Failed to get Linux CPU ID: {e}")
                cpu_id = platform.processor() or "unknown"
        else:  # macOS
            try:
                cpu_id = subprocess.check_output(
                    ['sysctl', '-n', 'machdep.cpu.brand_string'],
                    stderr=subprocess.DEVNULL,
                    timeout=5
                ).decode().strip()
            except Exception as e:
                logger.debug(f"Failed to get macOS CPU ID: {e}")
                cpu_id = platform.processor() or "unknown"
        components.append(cpu_id or "unknown")
    except Exception as e:
        logger.warning(f"Failed to get CPU ID: {e}")
        components.append(platform.processor() or "unknown")
    
    # 2. MAC Address (Primary Network Interface)
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) 
                        for i in range(0, 8*6, 8)][::-1])
        components.append(mac)
    except Exception as e:
        logger.warning(f"Failed to get MAC address: {e}")
        components.append("unknown-mac")
    
    # 3. Disk Serial Number
    try:
        if platform.system() == "Windows":
            try:
                # Get first disk serial
                result = subprocess.check_output(
                    'wmic diskdrive get serialnumber',
                    shell=True,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                ).decode().strip()
                disk_id = result.split('\n')[1].strip() if '\n' in result else "unknown"
                components.append(disk_id or "unknown")
            except Exception as e:
                logger.debug(f"Failed to get Windows disk serial: {e}")
                components.append("unknown-disk")
        elif platform.system() == "Linux":
            try:
                # Get first disk serial
                result = subprocess.check_output(
                    ['lsblk', '-o', 'SERIAL', '-n'],
                    stderr=subprocess.DEVNULL,
                    timeout=5
                ).decode().strip()
                disk_id = result.split('\n')[0] if result else "unknown"
                components.append(disk_id or "unknown")
            except Exception as e:
                logger.debug(f"Failed to get Linux disk serial: {e}")
                components.append("unknown-disk")
        else:  # macOS
            try:
                # Get disk serial
                result = subprocess.check_output(
                    ['system_profiler', 'SPStorageDataType'],
                    stderr=subprocess.DEVNULL,
                    timeout=10
                ).decode()
                # Extract serial from output (simplified)
                if 'Serial Number' in result:
                    disk_id = result.split('Serial Number')[1].split('\n')[0].strip()
                else:
                    disk_id = "unknown"
                components.append(disk_id)
            except Exception as e:
                logger.debug(f"Failed to get macOS disk serial: {e}")
                components.append("unknown-disk")
    except Exception as e:
        logger.warning(f"Failed to get disk serial: {e}")
        components.append("unknown-disk")
    
    # 4. OS Information
    components.append(platform.system())  # Windows, Linux, Darwin
    components.append(platform.release())  # OS version
    
    # 5. Machine Name (additional identifier)
    try:
        components.append(platform.node())  # Hostname
    except:
        components.append("unknown-host")
    
    # Generate hash from all components
    machine_string = "|".join(str(c) for c in components)
    machine_id = hashlib.sha256(machine_string.encode()).hexdigest()[:32]
    
    # Cache the result
    _cached_machine_id = machine_id
    
    logger.debug(f"Generated machine ID: {machine_id[:8]}... (from {len(components)} components)")
    
    return machine_id

def verify_machine_id(expected_machine_id: str, allow_one_change: bool = True) -> tuple[bool, str]:
    """
    Verify that current machine ID matches expected machine ID.
    
    Args:
        expected_machine_id: The machine ID the license is bound to
        allow_one_change: If True, allow one machine change (for hardware upgrades)
    
    Returns:
        Tuple of (is_valid, reason)
    """
    if not expected_machine_id or expected_machine_id == "unbound":
        return (True, "License not bound to machine")
    
    current_machine_id = get_machine_id()
    
    if current_machine_id == expected_machine_id:
        return (True, "Machine ID matches")
    else:
        if allow_one_change:
            return (False, f"Machine ID mismatch. Expected: {expected_machine_id[:8]}..., Got: {current_machine_id[:8]}... (one change allowed)")
        else:
            return (False, f"License is bound to another machine. Expected: {expected_machine_id[:8]}..., Got: {current_machine_id[:8]}...")

def clear_machine_id_cache():
    """Clear cached machine ID (useful for testing)"""
    global _cached_machine_id
    _cached_machine_id = None

