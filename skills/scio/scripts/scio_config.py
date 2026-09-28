"""Harness-independent MCP commands. Pure data: no environment reads, files or subprocesses."""
from pathlib import Path


def harness_name(name):
    return {"claude": "claude-code", "gemini": "gemini-cli", "kimi": "kimi-code"}.get(name, name)


def stdio_servers(skill_dir, interpreter, harness):
    """Adapters add their own environment, timeouts and permissions to these fresh definitions."""
    server_dir = Path(skill_dir) / "server"
    return {
        "scio": {"command": interpreter,
                 "args": [str(server_dir / "scio_bridge.py"), "--harness", harness_name(harness)]},
        "scio-local": {"command": interpreter, "args": [str(server_dir / "scio_local.py")]},
    }
