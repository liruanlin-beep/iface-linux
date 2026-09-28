from pathlib import Path
import re


DEFAULT_SLURM = {
    "job_name": "iface",
    "nodes": 1,
    "ntasks_per_node": 20,
    "time": "24:00:00",
    "partition": "",
    "account": "",
    "qos": "",
    "cpus_per_task": 1,
    "memory": "",
    "vasp_version": "6.4.3",
    "vasp_bin": "",
    "environment_init": "",
    "run_command": "srun vasp_std",
    "vasp_command": "srun vasp_std",
    "batch_mode": False,
    "submit_command": "sbatch Svasp.sh",
    "submit_script": "Svasp.sh",
}


class SlurmManager:
    def __init__(self, settings=None, job_name=None, script_name=None):
        self.settings = dict(DEFAULT_SLURM)
        self.settings.update(settings or {})
        self.job_name = sanitize_job_name(job_name or self.settings.get("job_name") or "iface")
        self.script_name = script_name or self.settings.get("submit_script") or "Svasp.sh"

    @classmethod
    def from_config(cls, config_data, job_name=None):
        config_data = config_data or {}
        settings = dict(config_data.get("slurm", {}))
        settings.setdefault("submit_script", config_data.get("submit_script", config_data.get("slurm_script_name", "Svasp.sh")))
        return cls(settings, job_name=settings.get("job_name") or job_name)

    def render(self):
        nodes = _positive_int(self.settings.get("nodes"), 1, 'Nodes')
        ntasks = _positive_int(self.settings.get("ntasks_per_node"), 20, 'Tasks per node')
        cpus_per_task = _positive_int(self.settings.get("cpus_per_task"), 1, 'CPUs per task')
        time_limit = str(self.settings.get("time") or "24:00:00").strip()
        if not re.fullmatch(r"(?:\d+-)?\d{1,3}:\d{2}:\d{2}", time_limit):
            raise ValueError(f'Invalid Slurm time format: {time_limit}')
        vasp_bin = str(self.settings.get("vasp_bin") or "").strip()
        run_command = str(
            self.settings.get("run_command")
            or self.settings.get("vasp_command")
            or "srun vasp_std"
        ).strip()
        if not run_command:
            raise ValueError('VASP run command cannot be empty')
        batch_mode = bool(self.settings.get("batch_mode", False))
        if batch_mode:
            run_block = f"""for i in *; do
    if [ -d "$i" ]; then
        cd "$i"
        {run_command}
        cd "$OLDPWD"
    fi
done"""
        else:
            run_block = run_command
        directives = [
            f"#SBATCH --job-name={self.job_name}",
            f"#SBATCH --nodes={nodes}",
            f"#SBATCH --ntasks-per-node={ntasks}",
            f"#SBATCH --cpus-per-task={cpus_per_task}",
            f"#SBATCH --time={time_limit}",
            "#SBATCH --output=slurm-%j.out",
            "#SBATCH --error=slurm-%j.err",
        ]
        for key, directive in (
            ("partition", "partition"),
            ("account", "account"),
            ("qos", "qos"),
            ("memory", "mem"),
        ):
            value = str(self.settings.get(key) or "").strip()
            if value:
                directives.append(f"#SBATCH --{directive}={value}")
        environment_init = str(
            self.settings.get("environment_init")
            or self.settings.get("submit_init_command")
            or ""
        ).strip()
        init_block = environment_init + "\n" if environment_init else ""
        path_block = f'export PATH="{vasp_bin}:$PATH"\n' if vasp_bin else ""
        return f"""#!/bin/bash
{chr(10).join(directives)}

set -o pipefail

ulimit -s unlimited

{init_block}{path_block}

{run_block}
"""

    def write(self, path_or_dir):
        path = Path(path_or_dir)
        if path.suffix and not path.is_dir():
            output_path = path
            output_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
            output_path = path / self.script_name
        output_path.write_text(self.render(), encoding="utf-8", newline="\n")
        return output_path


def sanitize_job_name(value):
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    text = text.strip("_.-")[:64]
    return text or "iface_job"


def _positive_int(value, default, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    if number <= 0:
        raise ValueError(f'{label} must be positive')
    return number


def render_slurm(settings, job_name="iface"):
    return SlurmManager.from_config(settings, job_name=job_name).render()


def write_slurm(path, settings, job_name="iface"):
    return SlurmManager.from_config(settings, job_name=job_name).write(path)
