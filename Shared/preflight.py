"""
Preflight validation — runs before any other logic.
Any failed check halts execution with a human-readable explanation.
"""
import os
import shutil
import socket
import pathlib
import platform
import logging


def run_all_checks(config: dict) -> list:
    checks = []
    shared_dir = pathlib.Path(__file__).parent

    # 1. Disk space — require at least 500 MB headroom
    try:
        free = shutil.disk_usage(str(shared_dir)).free
        required = 500 * 1024 ** 2  # 500 MB
        checks.append({
            "name": "disk_space",
            "passed": free > required,
            "detail": f"{free / 1024**2:.0f} MB free",
            "remedy": "Free up at least 500 MB of space on the drive before starting.",
        })
    except Exception as e:
        checks.append({
            "name": "disk_space",
            "passed": False,
            "detail": str(e),
            "remedy": "Unable to determine disk space. Verify drive health.",
        })

    # 2. Write permission on chat_data directory
    chat_data = shared_dir / config.get("chat_data_dir", "chat_data").replace("Shared/", "")
    chat_data.mkdir(parents=True, exist_ok=True)
    try:
        test_file = chat_data / ".write_test"
        test_file.touch()
        test_file.unlink()
        checks.append({"name": "write_permission", "passed": True, "detail": str(chat_data)})
    except PermissionError:
        checks.append({
            "name": "write_permission",
            "passed": False,
            "detail": str(chat_data),
            "remedy": "The drive may be mounted read-only. Re-insert and check OS mount flags.",
        })

    # 3. UI port availability
    ui_port = config.get("ui_port", 5000)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        result = s.connect_ex(("127.0.0.1", ui_port))
    checks.append({
        "name": "port_available",
        "passed": result != 0,
        "detail": f"Port {ui_port}",
        "remedy": f"Another process is already using port {ui_port}. Change ui_port in config.json.",
    })

    return checks


def print_results(checks: list) -> bool:
    """Print check results. Returns True if all passed."""
    all_passed = True
    for check in checks:
        status = "PASS" if check["passed"] else "FAIL"
        color = "\033[92m" if check["passed"] else "\033[91m"
        reset = "\033[0m"
        detail = f"  ({check.get('detail', '')})" if check.get("detail") else ""
        print(f"  {color}[{status}]{reset}  {check['name']}{detail}")
        if not check["passed"]:
            all_passed = False
            remedy = check.get("remedy")
            if remedy:
                print(f"         Resolution: {remedy}")
            logging.error("Preflight FAILED: %s — %s", check["name"], check.get("detail", ""))
    return all_passed
