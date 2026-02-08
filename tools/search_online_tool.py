import subprocess


def search_online(query: str, vertical: str = "web", limit: int = 10) -> str:
    """Search the web using Brave Search. Returns structured JSON results with title, url, and snippet for each result."""
    cmd = [
        "fish", "-c",
        "search_online -o json -v " + vertical + " -L " + str(limit) + " " + repr(query),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout if result.returncode == 0 else "Error: " + result.stderr
