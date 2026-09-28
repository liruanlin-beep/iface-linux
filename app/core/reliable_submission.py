import re
import shlex


class SubmissionOutcomeUnknown(RuntimeError):
    """The scheduler may have accepted the job, so automatic retry is unsafe."""


def parse_sbatch_job_id(text):
    value = str(text or "").strip()
    patterns = (
        r"Submitted\s+batch\s+job\s+(\d+)",
        r"^\s*(\d+)(?:;[^\s]+)?\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1)
    return ""


def ensure_parsable_sbatch(command, script_name="Svasp.sh"):
    command = str(command or "").strip()
    if not command:
        command = f"sbatch {shlex.quote(script_name)}"
    tokens = shlex.split(command)
    if not tokens or tokens[0] != "sbatch":
        return command
    if "--parsable" not in tokens:
        tokens.insert(1, "--parsable")
    return shlex.join(tokens)


def parse_reconciliation_job_id(text, expected_name=""):
    expected_name = str(expected_name or "").strip()
    candidates = set()
    for line in str(text or "").splitlines():
        fields = [field.strip() for field in line.split("|")]
        if not fields or not fields[0].isdigit():
            continue
        if expected_name and (len(fields) < 2 or fields[1] != expected_name):
            continue
        candidates.add(fields[0])
    if len(candidates) > 1:
        raise SubmissionOutcomeUnknown('Multiple Slurm jobs have the same name; unique reconciliation is impossible, so automatic association or resubmission is blocked')
    return next(iter(candidates), "")


class ReliableSlurmSubmitter:
    def __init__(
        self,
        ssh_manager,
        remote_dir,
        init_command="",
        use_login_shell=True,
        username="",
    ):
        self.ssh = ssh_manager
        self.remote_dir = remote_dir
        self.init_command = init_command
        self.use_login_shell = bool(use_login_shell)
        self.username = username or getattr(ssh_manager, "username", "")

    def submit(self, command, script_name="Svasp.sh", job_name=""):
        parsable = ensure_parsable_sbatch(command, script_name)
        try:
            exit_code, out, err, final_command = self.ssh.run_remote_command(
                parsable,
                self.remote_dir,
                self.init_command,
                self.use_login_shell,
            )
        except Exception as exc:
            job_id = self.reconcile(job_name)
            if job_id:
                return job_id, f'Submission connection failed, but Slurm reconciliation found JobID={job_id}', parsable
            raise SubmissionOutcomeUnknown(
                f'sbatch communication failed; submission is uncertain and automatic retry is blocked: {exc}'
            ) from exc
        text = (out + "\n" + err).strip()
        job_id = parse_sbatch_job_id(text)
        if exit_code == 0 and job_id:
            return job_id, text, final_command
        if exit_code != 0:
            raise RuntimeError(f'sbatch exit code {exit_code}：{text}')
        job_id = self.reconcile(job_name)
        if job_id:
            return job_id, f'sbatch did not return a standard JobID; reconciliation found {job_id}', final_command
        raise SubmissionOutcomeUnknown(
            'sbatch exited with code 0 without a JobID, and squeue/sacct reconciliation failed; automatic retry is blocked.'
        )

    def reconcile(self, job_name):
        job_name = str(job_name or "").strip()
        if not job_name:
            return ""
        user_part = f"-u {shlex.quote(self.username)} " if self.username else ""
        quoted_name = shlex.quote(job_name)
        commands = (
            f"squeue -h {user_part}-n {quoted_name} -o '%A|%j|%T'",
            f"sacct -n -X {user_part}--name {quoted_name} -o JobIDRaw,JobName,State --parsable2",
        )
        for command in commands:
            try:
                code, out, _err, _final = self.ssh.run_remote_command(
                    command,
                    self.remote_dir,
                    self.init_command,
                    self.use_login_shell,
                )
            except Exception:
                continue
            if code == 0:
                try:
                    job_id = parse_reconciliation_job_id(out, job_name)
                except SubmissionOutcomeUnknown:
                    # Do not let a second source hide an ambiguous first result.
                    return ""
                if job_id:
                    return job_id
        return ""
