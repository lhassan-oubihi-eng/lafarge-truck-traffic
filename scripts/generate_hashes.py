import hashlib
import glob
import os
import subprocess

os.makedirs(".pip-hashes", exist_ok=True)
subprocess.run(
    [
        "C:/Python314/python.exe",
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--dest",
        ".pip-hashes",
        "fastapi==0.115.0",
        "uvicorn==0.30.6",
        "prometheus-client==0.20.0",
    ],
    check=True,
)

for path in sorted(glob.glob(".pip-hashes/*")):
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    print(f"{os.path.basename(path)} {digest}")
