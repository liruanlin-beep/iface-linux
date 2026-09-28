import posixpath
import shlex


SLURM_DIAGNOSTIC_COMMAND = (
    "hostname && whoami && pwd && echo SHELL=$SHELL && "
    "getent passwd $USER | awk -F: '{print \"LOGIN_SHELL=\" $7}' && "
    "(command -v sbatch || which sbatch || ls -l /opt/slurm/bin/sbatch) && "
    "(sbatch --version || /opt/slurm/bin/sbatch --version) && "
    "(sinfo || /opt/slurm/bin/sinfo) && "
    "(squeue -u $USER || /opt/slurm/bin/squeue -u $USER)"
)


def classify_submit_error(stderr="", stdout=""):
    text = f"{stdout or ''}\n{stderr or ''}".lower()
    if (
        "command not found: squeue" in text
        or "squeue: command not found" in text
        or "squeue: not found" in text
    ):
        return "SQUEUE_NOT_FOUND"
    if "command not found: sbatch" in text or "sbatch: command not found" in text or "sbatch: not found" in text:
        return "SBATCH_NOT_FOUND"
    if "unable to contact slurm controller" in text or "connect failure" in text:
        return "SLURM_CONTROLLER_UNREACHABLE"
    if "invalid account" in text:
        return "SLURM_INVALID_ACCOUNT"
    if "invalid partition" in text:
        return "SLURM_INVALID_PARTITION"
    if "permission denied" in text:
        return "PERMISSION_DENIED"
    if "no such file or directory" in text:
        return "SCRIPT_NOT_FOUND"
    return "UNKNOWN"


def submit_error_title(error_type):
    return {
        "SQUEUE_NOT_FOUND": 'squeue command not found',
        "SBATCH_NOT_FOUND": 'sbatch command not found',
        "SLURM_CONTROLLER_UNREACHABLE": 'Slurm controller unreachable',
        "SLURM_INVALID_ACCOUNT": 'Invalid Slurm account configuration',
        "SLURM_INVALID_PARTITION": 'Invalid Slurm partition configuration',
        "PERMISSION_DENIED": 'Permission denied',
        "SCRIPT_NOT_FOUND": 'Submission script does not exist',
    }.get(error_type, 'Submission failed')


def submit_error_hint(error_type, command="sbatch Svasp.sh"):
    if error_type == "SQUEUE_NOT_FOUND":
        return (
            'SSH is connected, but squeue is absent from PATH in the noninteractive shell.\nRun Test Slurm Environment. Set initialization to source /etc/profile, source ~/.bashrc or module load slurm, or configure the query command as /opt/slurm/bin/squeue -u {username}.'
        )
    if error_type == "SLURM_CONTROLLER_UNREACHABLE":
        return (
            f'sbatch executed but could not contact the Slurm controller.\nThis usually does not indicate a problem with POSCAR/INCAR/KPOINTS/POTCAR or Svasp.sh.\n\nTest in a terminal:\nsinfo\nsqueue -u $USER\n{command}\n\nIf this also fails in a terminal, ask the administrator to check Slurm or the submission node.\nIf it works there, check the environment initialization command, such as source ~/.bashrc or module load slurm.'
        )
    if error_type == "SBATCH_NOT_FOUND":
        return (
            'sbatch is unavailable in the current shell.\nTry source ~/.bashrc, source /etc/profile or module load slurm in submission settings and enable bash -lc.\nIf Slurm is installed in /opt/slurm/bin, use /opt/slurm/bin/sbatch Svasp.sh.'
        )
    if error_type == "SLURM_INVALID_ACCOUNT":
        return 'Invalid Slurm account. Check account/project in Svasp.sh or contact the administrator.'
    if error_type == "SLURM_INVALID_PARTITION":
        return 'Invalid Slurm partition. Check the partition in Svasp.sh.'
    if error_type == "PERMISSION_DENIED":
        return 'Permission denied. Check submission permissions and read/execute permissions on Svasp.sh.'
    if error_type == "SCRIPT_NOT_FOUND":
        return 'No submission script was found in the current remote directory. Check the path and script name.'
    return 'Check stdout/stderr in the log and run the diagnostic commands in a terminal for comparison.'


def troubleshooting_commands(remote_dir, submit_command="sbatch Svasp.sh"):
    remote_dir = str(remote_dir or ".").replace("\\", "/").rstrip("/") or "."
    return "\n".join(
        [
            f"cd {shlex.quote(remote_dir)}",
            "hostname",
            "whoami",
            "pwd",
            "echo $SHELL",
            "getent passwd $USER | awk -F: '{print \"LOGIN_SHELL=\" $7}'",
            "command -v sbatch",
            "ls -l /opt/slurm/bin/sbatch",
            "sbatch --version",
            "/opt/slurm/bin/sbatch --version",
            "sinfo",
            "squeue -u $USER",
            submit_command or "sbatch Svasp.sh",
        ]
    )


def normalize_remote_dir(remote_dir):
    text = str(remote_dir or ".").strip().replace("\\", "/")
    return posixpath.normpath(text or ".")
