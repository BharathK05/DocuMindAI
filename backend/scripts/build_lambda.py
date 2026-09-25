"""Build the AWS Lambda deployment packages.

    python scripts/build_lambda.py --arch arm64      # what AWS runs (Graviton: cheaper per GB-s)
    python scripts/build_lambda.py --arch x86_64     # used by CI to import-test on its runner

Outputs in ``dist/``:
  * ``layer-<arch>.zip``   third-party dependencies (``python/``) + pre-fetched tiktoken files.
                           Changes rarely, so code-only deploys don't re-upload tens of MB.
  * ``function.zip``       our code + ``run.sh`` (Python + bytecode: architecture-independent).
                           One zip serves both functions:
                             API    -> handler ``run.sh`` behind the Lambda Web Adapter layer
                             worker -> handler ``documind.lambda_worker.handler``

Zips are deterministic (sorted entries, fixed timestamps): identical inputs give identical
hashes, so Terraform only redeploys when something actually changed.
"""

import argparse
import compileall
import hashlib
import os
import py_compile
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PYTHON_VERSION = "3.13"  # must match the Lambda runtime (python3.13)
# The python3.13 runtime runs on Amazon Linux 2023 (glibc 2.34), so wheels built for glibc 2.28
# (what NumPy >= 2.3 publishes) and the older manylinux2014 (glibc 2.17) are both compatible.
PLATFORMS = {
    "arm64": ("manylinux_2_28_aarch64", "manylinux2014_aarch64"),
    "x86_64": ("manylinux_2_28_x86_64", "manylinux2014_x86_64"),
}
# boto3/botocore ship in the Lambda Python runtime; bundling them would add ~25 MB for nothing.
PROVIDED_BY_RUNTIME = {"boto3", "botocore"}
# The API runs as a plain ASGI server behind the Lambda Web Adapter (which enables response
# streaming). Plain uvicorn, not uvicorn[standard]: uvloop/httptools add size, not value here.
EXTRA_RUNTIME_DEPS = ["uvicorn~=0.53.0"]
TIKTOKEN_ENCODINGS = ("cl100k_base", "o200k_base")
FIXED_TIMESTAMP = (2020, 1, 1, 0, 0, 0)

# AWS limits: 50 MB per zip uploaded directly, 250 MB unzipped for function + all layers.
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNZIPPED_BYTES = 250 * 1024 * 1024

RUN_SH = """#!/bin/sh
# Entry point for the API function. The Lambda Web Adapter forwards HTTP requests to this server.
exec python -m uvicorn documind.api.main:app --host 0.0.0.0 --port "${PORT:-8080}"
"""


def runtime_requirements() -> list[str]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    deps: list[str] = project["dependencies"]
    keep = [d for d in deps if d.split("~")[0].split("=")[0].strip() not in PROVIDED_BY_RUNTIME]
    return keep + EXTRA_RUNTIME_DEPS


def install_dependencies(target: Path, arch: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-compile",
            "--target",
            str(target),
            *(arg for tag in PLATFORMS[arch] for arg in ("--platform", tag)),
            "--implementation",
            "cp",
            "--python-version",
            PYTHON_VERSION,
            "--only-binary=:all:",  # never compile locally: wheels must match Lambda's Linux
            *runtime_requirements(),
        ],
        check=True,
    )
    # Prune what Lambda never uses: runtime-provided SDKs, caches, console-script launchers
    # (pip generates host-specific ones, which also made builds non-reproducible) and RECORD
    # files (only needed by `pip uninstall`, and they hash those launchers).
    for pattern in ("boto3", "botocore", "boto3-*", "botocore-*", "bin", "**/__pycache__"):
        for path in target.glob(pattern):
            shutil.rmtree(path, ignore_errors=True)
    for record in target.glob("*.dist-info/RECORD"):
        record.unlink()


def prefetch_tiktoken(cache_dir: Path) -> None:
    """Download tokenizer files at build time; at runtime set TIKTOKEN_CACHE_DIR to this folder
    (/opt/tiktoken_cache), otherwise every cold start downloads them from the internet."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    code = "import tiktoken\n" + "".join(
        f"tiktoken.get_encoding({name!r})\n" for name in TIKTOKEN_ENCODINGS
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "TIKTOKEN_CACHE_DIR": str(cache_dir)},
    )


def precompile(source: Path, runtime_path: str) -> None:
    """Ship bytecode. Lambda's code directories are read-only, so without .pyc files Python
    recompiles every module on every cold start. Measured in the official Lambda image:
    importing the API takes ~1.9 s without bytecode vs ~0.7 s with it. "Unchecked hash" pycs
    skip mtime checks and, with ``ddir`` set to the Lambda path, are byte-identical across
    build machines."""
    if sys.version_info[:2] != tuple(int(p) for p in PYTHON_VERSION.split(".")):
        sys.exit(f"Build with Python {PYTHON_VERSION}: bytecode must match the Lambda runtime.")
    ok = compileall.compile_dir(
        source,
        ddir=runtime_path,
        quiet=1,
        workers=0,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    if not ok:
        sys.exit(f"Bytecode compilation failed in {source}")


def write_zip(source: Path, destination: Path) -> None:
    files = sorted(p for p in source.rglob("*") if p.is_file())
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), FIXED_TIMESTAMP)
            executable = path.suffix == ".sh"
            info.external_attr = (0o755 if executable else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())


def tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build(arch: str, out: Path) -> None:
    work = out / "build" / arch
    shutil.rmtree(work, ignore_errors=True)
    layer_dir, function_dir = work / "layer", work / "function"

    print(f"Installing dependencies for Linux {arch} / Python {PYTHON_VERSION}...")
    install_dependencies(layer_dir / "python", arch)
    prefetch_tiktoken(layer_dir / "tiktoken_cache")

    print("Copying application code...")
    shutil.copytree(
        BACKEND / "src" / "documind",
        function_dir / "documind",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (function_dir / "run.sh").write_text(RUN_SH, encoding="utf-8", newline="\n")

    print("Precompiling bytecode...")
    precompile(layer_dir / "python", "/opt/python")  # where Lambda mounts layers
    precompile(function_dir, "/var/task")  # where Lambda unpacks the function

    layer_zip, function_zip = out / f"layer-{arch}.zip", out / "function.zip"
    write_zip(layer_dir, layer_zip)
    write_zip(function_dir, function_zip)

    unzipped = tree_size(layer_dir) + tree_size(function_dir)
    rows = [
        (layer_zip.name, layer_zip.stat().st_size, tree_size(layer_dir), sha256(layer_zip)),
        (
            function_zip.name,
            function_zip.stat().st_size,
            tree_size(function_dir),
            sha256(function_zip),
        ),
    ]
    print(f"\n{'package':<22}{'zipped':>10}{'unzipped':>11}  sha256")
    for name, zipped, raw, digest in rows:
        print(f"{name:<22}{zipped / 1e6:>8.1f}MB{raw / 1e6:>9.1f}MB  {digest}")
    print(f"{'total unzipped':<22}{'':>10}{unzipped / 1e6:>9.1f}MB  (limit 250 MB)")

    problems = [
        f"{n} is {z / 1e6:.1f} MB zipped (limit 50 MB)" for n, z, _, _ in rows if z > MAX_ZIP_BYTES
    ]
    if unzipped > MAX_UNZIPPED_BYTES:
        problems.append(f"unzipped total {unzipped / 1e6:.1f} MB exceeds 250 MB")
    if problems:
        sys.exit("Package too large: " + "; ".join(problems))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--arch", choices=sorted(PLATFORMS), default="arm64")
    parser.add_argument("--out", type=Path, default=BACKEND / "dist")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    build(args.arch, args.out)


if __name__ == "__main__":
    main()
