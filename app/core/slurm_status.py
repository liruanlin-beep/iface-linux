import re


def parse_squeue(text):
    rows = []
    for line in (text or "").splitlines():
        parts = [part.strip() for part in line.split("|", 4)]
        if len(parts) == 5 and parts[0]:
            rows.append(tuple(parts))
    return rows


def parse_sacct(text):
    """Return the newest state for each top-level numeric Slurm JobID."""
    states = {}
    for line in (text or "").splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        job_id = parts[0].split(".", 1)[0].split("_", 1)[0]
        if not re.fullmatch(r"\d+", job_id):
            continue
        state = parts[1].split("+", 1)[0].strip().upper()
        if state:
            states[job_id] = state
    return states
