"""
Structured error system — every failure mode has a code, message, and remedy.
Raw exceptions must never surface to the user.
"""


class AppError(Exception):
    def __init__(self, code: str, message: str, remedy: str, docs_ref: str = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy = remedy
        self.docs_ref = docs_ref

    def render(self):
        print(f"\n  ERROR [{self.code}]")
        print(f"  {self.message}")
        print(f"  Resolution: {self.remedy}")
        if self.docs_ref:
            print(f"  See: {self.docs_ref}")
        print()


ERRORS = {
    "ENGINE_NOT_FOUND": AppError(
        code="ENGINE_NOT_FOUND",
        message="The Ollama engine binary was not found for your operating system.",
        remedy="Run the install script for your OS: Windows/install.bat, Mac/install.sh, or Linux/install.sh",
    ),
    "ENGINE_NOT_RUNNING": AppError(
        code="ENGINE_NOT_RUNNING",
        message="Cannot reach the Ollama engine. It may not be running.",
        remedy="Start Ollama on your machine, or run the appropriate start script for your OS.",
    ),
    "MODEL_NOT_FOUND": AppError(
        code="MODEL_NOT_FOUND",
        message="No model file was found in Shared/models/.",
        remedy="Run the installer and select a model to download, or manually place a .gguf file in Shared/models/",
    ),
    "MODEL_CORRUPT": AppError(
        code="MODEL_CORRUPT",
        message="The model file failed integrity verification (SHA-256 mismatch).",
        remedy="Delete the file from Shared/models/ and re-run the installer to download a fresh copy.",
    ),
    "PORT_OCCUPIED": AppError(
        code="PORT_OCCUPIED",
        message="The configured UI port is already in use by another process.",
        remedy="Edit config.json and change ui_port to an unused port.",
    ),
    "WRITE_PERMISSION_DENIED": AppError(
        code="WRITE_PERMISSION_DENIED",
        message="Cannot write to the Shared/chat_data directory.",
        remedy="Check that the drive is not mounted read-only. Re-insert and verify OS mount flags.",
    ),
    "DISK_SPACE_LOW": AppError(
        code="DISK_SPACE_LOW",
        message="Insufficient disk space to operate safely.",
        remedy="Free up at least 500 MB of space on the drive before starting.",
    ),
    "CONFIG_INVALID": AppError(
        code="CONFIG_INVALID",
        message="config.json is missing or contains invalid JSON.",
        remedy="Restore or recreate config.json from the repository root.",
    ),
}
