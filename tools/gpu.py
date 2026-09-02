"""GPU tools — NVIDIA status via nvidia-smi."""
from __future__ import annotations

import subprocess

from tools.base import Tool


def gpu_status(**kwargs) -> dict:
    proc = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
    if proc.returncode != 0:
        return {"available": False,
                "error": proc.stderr.strip() or "nvidia-smi failed"}
    return {"available": True, "output": proc.stdout.strip()[:4000]}


def gpu_temperature(**kwargs) -> dict:
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,"
                       "memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()}
    out = proc.stdout.strip()
    if not out:
        return {"error": "no output"}
    temp, util, used, total = (out.split(",") + ["", "", "", ""])[:4]
    return {"temperature_c": temp.strip(), "utilization_pct": util.strip(),
            "memory_used_mb": used.strip(), "memory_total_mb": total.strip()}


GPU_TOOLS = [
    Tool("gpu_status", "Show NVIDIA GPU status summary.",
         {"type": "object", "properties": {}}, fn=gpu_status),
    Tool("gpu_temperature", "Show GPU temperature, util, memory.",
         {"type": "object", "properties": {}}, fn=gpu_temperature),
]
