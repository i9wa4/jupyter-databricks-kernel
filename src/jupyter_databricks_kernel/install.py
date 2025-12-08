"""Kernel installation script."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

KERNEL_NAME = "databricks"
KERNEL_SPEC = {
    "argv": [
        sys.executable,
        "-m",
        "jupyter_databricks_kernel",
        "-f",
        "{connection_file}",
    ],
    "display_name": "Databricks",
    "language": "python",
}


def install_kernel(user: bool = False, prefix: str | None = None) -> None:
    """Install the Databricks kernel spec.

    Args:
        user: Install to user directory (~/.local/share/jupyter/kernels/)
        prefix: Install to specific prefix (e.g., sys.prefix for venv)
    """
    from jupyter_client.kernelspec import KernelSpecManager

    with tempfile.TemporaryDirectory() as td:
        kernel_dir = Path(td)
        with open(kernel_dir / "kernel.json", "w") as f:
            json.dump(KERNEL_SPEC, f, indent=2)

        ksm = KernelSpecManager()
        ksm.install_kernel_spec(
            str(kernel_dir),
            kernel_name=KERNEL_NAME,
            user=user,
            prefix=prefix,
        )

    dest = ksm.get_kernel_spec(KERNEL_NAME).resource_dir
    print(f"Installed kernelspec {KERNEL_NAME} in {dest}")


def main() -> None:
    """CLI entry point for kernel installation."""
    parser = argparse.ArgumentParser(description="Install the Databricks kernel")
    parser.add_argument(
        "--user",
        action="store_true",
        help="Install for the current user (~/.local/share/jupyter/kernels/)",
    )
    parser.add_argument(
        "--sys-prefix",
        action="store_true",
        help="Install to sys.prefix (current venv). This is the default.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        help="Install to a specific prefix",
    )

    args = parser.parse_args()

    if args.user:
        install_kernel(user=True)
    elif args.prefix:
        install_kernel(prefix=args.prefix)
    else:
        # Default: --sys-prefix
        install_kernel(prefix=sys.prefix)


if __name__ == "__main__":
    main()
