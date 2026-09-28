import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
SUPPORTED_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")

SAFE_INCAR_KEYS = {
    "ADDGRID",
    "ALGO",
    "AMIX",
    "AMIX_MAG",
    "BMIX",
    "BMIX_MAG",
    "EDIFF",
    "EDIFFG",
    "EMAX",
    "EMIN",
    "ENCUT",
    "IBRION",
    "ISIF",
    "ISMEAR",
    "ISYM",
    "KPAR",
    "LASPH",
    "LCHARG",
    "LMAXMIX",
    "LORBIT",
    "LREAL",
    "LWAVE",
    "NCORE",
    "NEDOS",
    "NELM",
    "NELMIN",
    "NSW",
    "POTIM",
    "PREC",
    "SIGMA",
}

PROTECTED_INCAR_KEYS = {
    "AEXX",
    "AGGAC",
    "GGA",
    "HFSCREEN",
    "IVDW",
    "LDAU",
    "LDAUJ",
    "LDAUL",
    "LDAUTYPE",
    "LDAUU",
    "LHFCALC",
    "LUSE_VDW",
    "METAGGA",
    "PARAM1",
    "PARAM2",
}


@dataclass
class IncarSuggestion:
    key: str
    old_value: str
    new_value: str
    reason: str
    confidence: float


@dataclass
class AdvisorResult:
    summary: str
    diagnosis: tuple
    changes: tuple
    warnings: tuple
    stop_recommendation: str
    model: str
    usage: dict


def parse_incar(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'INCAR does not exist: {path}')
    result = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = re.split(r"[#!]", raw_line, maxsplit=1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            result[key] = value.strip()
    return result


def request_vasp_advice(
    api_key,
    model,
    incar_path,
    task_context="",
    timeout_seconds=90,
):
    api_key = str(api_key or "").strip()
    if not api_key:
        raise ValueError('Enter a DeepSeek API key.')
    if model not in SUPPORTED_MODELS:
        raise ValueError(f'Unsupported model: {model}')
    incar = parse_incar(incar_path)
    system_prompt = (
        'You are a controlled VASP 6.x parameter diagnostic assistant. Analyze only the supplied INCAR and error summary. Return one JSON object: {"summary":"", "diagnosis":[""], "changes":[{"key":"","old_value":"","new_value":"","reason":"","confidence":0.0}],"warnings":[""],"stop_recommendation":""}. Suggest only INCAR parameters for convergence, precision, relaxation and parallelism. Do not suggest or change POTCAR, potentials, element order, exchange-correlation functionals, DFT+U values, van der Waals schemes, structural coordinates or initial magnetic moments. Return an empty changes array without sufficient evidence. new_value must be a single line suitable for INCAR, with no commands or explanations.'
    )
    user_prompt = (
        f"Diagnose the following input and return permitted suggestions as JSON.\nCurrent INCAR:\n{json.dumps(incar, ensure_ascii=False, indent=2)}\nCalculation status and OUTCAR/OSZICAR error summary:\n{str(task_context or 'Not provided')[:20000]}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled", "reasoning_effort": "high"},
        "temperature": 0.1,
        "max_tokens": 2500,
        "stream": False,
    }
    if os.name == "nt":
        response_data = _windows_system_post(
            DEEPSEEK_ENDPOINT,
            api_key,
            payload,
            timeout_seconds,
        )
    else:
        response_data = _urllib_post(
            DEEPSEEK_ENDPOINT,
            api_key,
            payload,
            timeout_seconds,
        )
    try:
        content = response_data["choices"][0]["message"]["content"]
        answer = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError('The DeepSeek response is not a usable JSON suggestion.') from exc
    changes, validation_warnings = validate_suggestions(answer.get("changes"), incar)
    warnings = [str(item) for item in answer.get("warnings", []) if str(item).strip()]
    warnings.extend(validation_warnings)
    return AdvisorResult(
        summary=str(answer.get("summary") or 'The AI provided no summary.'),
        diagnosis=tuple(
            str(item) for item in answer.get("diagnosis", []) if str(item).strip()
        ),
        changes=tuple(changes),
        warnings=tuple(warnings),
        stop_recommendation=str(answer.get("stop_recommendation") or ""),
        model=str(response_data.get("model") or model),
        usage=dict(response_data.get("usage") or {}),
    )


def _urllib_post(url, api_key, payload, timeout_seconds):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "iface/2.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=float(timeout_seconds)
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:1000]
        raise RuntimeError(f'DeepSeek API returned HTTP {exc.code}：{detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Cannot connect to the DeepSeek API: {exc.reason}') from exc


def _windows_system_post(url, api_key, payload, timeout_seconds):
    """Use Windows' system HTTPS/proxy channel without exposing proxy settings."""
    script = r"""
$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$requestData = ([Console]::In.ReadToEnd() | ConvertFrom-Json)
$headers = @{
    Authorization = "Bearer $($requestData.api_key)"
    Accept = "application/json"
    "User-Agent" = "iface/2.0"
}
$body = $requestData.payload | ConvertTo-Json -Depth 30 -Compress
try {
    $result = Invoke-RestMethod -Uri $requestData.url -Method Post `
        -Headers $headers -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
        -TimeoutSec $requestData.timeout
    $result | ConvertTo-Json -Depth 40 -Compress
} catch {
    $status = ""
    $detail = $_.Exception.Message
    if ($_.Exception.Response) {
        try { $status = [int]$_.Exception.Response.StatusCode } catch {}
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $responseText = $reader.ReadToEnd()
            if ($responseText) { $detail = $responseText }
        } catch {}
    }
    [Console]::Error.WriteLine(("HTTP {0}: {1}" -f $status, $detail))
    exit 1
}
"""
    input_data = json.dumps(
        {
            "url": str(url),
            "api_key": str(api_key),
            "payload": payload,
            "timeout": max(5, int(float(timeout_seconds))),
        },
        ensure_ascii=False,
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            input=input_data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout_seconds) + 15,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Windows HTTPS request failed: {exc}') from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:1500]
        raise RuntimeError(f"DeepSeek API request failed: {detail or 'Windows HTTPS channel did not respond'}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('Cannot parse the DeepSeek API response.') from exc


def detect_windows_proxy():
    """Return the current user's explicit Windows proxy without saving it."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
            value = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
    except (ImportError, OSError, ValueError):
        return ""
    if not enabled or not value:
        return ""
    if "=" in value:
        mappings = {}
        for item in value.split(";"):
            if "=" in item:
                protocol, address = item.split("=", 1)
                mappings[protocol.strip().lower()] = address.strip()
        value = mappings.get("https") or mappings.get("http") or ""
    if not value:
        return ""
    return value if "://" in value else "http://" + value


def test_deepseek_connectivity(proxy_url="", timeout_seconds=15):
    """Confirm DNS/TLS/proxy reachability without requiring or sending an API key."""
    request = urllib.request.Request(
        "https://api.deepseek.com/models",
        headers={"Accept": "application/json", "User-Agent": "iface/2.0"},
        method="GET",
    )
    try:
        with _url_opener(proxy_url).open(
            request, timeout=float(timeout_seconds)
        ) as response:
            return f'Network reachable; server returned HTTP {response.status}。'
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return f'Network reachable; DeepSeek returned HTTP {exc.code}; enter a valid API key to make requests.'
        raise RuntimeError(f'DeepSeek responded with HTTP {exc.code}。') from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f'Connection failed: {reason}') from exc


def _url_opener(proxy_url=""):
    proxy_url = str(proxy_url or "").strip()
    if not proxy_url:
        return urllib.request.build_opener()
    if "://" not in proxy_url:
        proxy_url = "http://" + proxy_url
    if not re.fullmatch(r"https?://[^/\s:]+:\d{1,5}", proxy_url):
        raise ValueError('Use a proxy URL such as http://127.0.0.1:7892.')
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )


def validate_suggestions(raw_changes, current_incar):
    accepted = []
    warnings = []
    for raw in raw_changes or []:
        if not isinstance(raw, dict):
            warnings.append('Ignored an AI change that was not an object.')
            continue
        key = str(raw.get("key") or "").strip().upper()
        if key in PROTECTED_INCAR_KEYS:
            warnings.append(f'Blocked protected parameter {key}: the AI cannot change the functional, DFT+U or van der Waals scheme.')
            continue
        if key not in SAFE_INCAR_KEYS:
            warnings.append(f"Ignored parameter outside the permitted list: {key or '(empty)'}。")
            continue
        value = str(raw.get("new_value") or "").strip()
        try:
            _validate_incar_value(key, value)
        except ValueError as exc:
            warnings.append(f'Rejected {key}：{exc}')
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        accepted.append(
            IncarSuggestion(
                key=key,
                old_value=str(current_incar.get(key, raw.get("old_value") or "")),
                new_value=value,
                reason=str(raw.get("reason") or 'The AI provided no reason.'),
                confidence=confidence,
            )
        )
    return accepted, warnings


def _validate_incar_value(key, value):
    if not value:
        raise ValueError('The new value cannot be empty')
    if len(value) > 120 or any(character in value for character in "\r\n;&|`$"):
        raise ValueError('The new value contains unsafe characters or is too long')
    numeric_ranges = {
        "ENCUT": (100, 2000),
        "EDIFF": (1e-12, 1e-2),
        "NELM": (1, 1000),
        "NELMIN": (1, 100),
        "NSW": (0, 2000),
        "POTIM": (0.01, 5.0),
        "SIGMA": (0.001, 2.0),
        "NEDOS": (100, 100000),
        "KPAR": (1, 1024),
        "NCORE": (1, 1024),
    }
    if key in numeric_ranges:
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError('must be numeric') from exc
        low, high = numeric_ranges[key]
        if not low <= number <= high:
            raise ValueError(f'value must be within {low:g}–{high:g} range')


def apply_incar_suggestions(incar_path, suggestions):
    """Apply user-approved suggestions and retain a timestamped backup."""
    path = Path(incar_path)
    if not path.is_file():
        raise FileNotFoundError(f'INCAR does not exist: {path}')
    suggestions = list(suggestions)
    if not suggestions:
        raise ValueError('No suggested changes were selected.')
    replacements = {}
    for item in suggestions:
        if item.key not in SAFE_INCAR_KEYS or item.key in PROTECTED_INCAR_KEYS:
            raise ValueError(f'Parameter {item.key} cannot be written automatically.')
        _validate_incar_value(item.key, item.new_value)
        replacements[item.key] = item.new_value

    original = path.read_text(encoding="utf-8", errors="ignore")
    updated_lines = []
    seen = set()
    pattern = re.compile(r"^(\s*)([A-Za-z][A-Za-z0-9_]*)(\s*=\s*)(.*)$")
    for line in original.splitlines():
        match = pattern.match(line)
        if not match:
            updated_lines.append(line)
            continue
        key = match.group(2).upper()
        if key not in replacements:
            updated_lines.append(line)
            continue
        value_and_comment = match.group(4)
        comment_match = re.search(r"(\s+[#!].*)$", value_and_comment)
        comment = comment_match.group(1) if comment_match else ""
        updated_lines.append(
            f"{match.group(1)}{key}{match.group(3)}{replacements[key]}{comment}"
        )
        seen.add(key)
    missing = [key for key in replacements if key not in seen]
    if missing:
        updated_lines.append("")
        updated_lines.append('# iface AI suggestion (confirmed by the user)')
        updated_lines.extend(f"{key} = {replacements[key]}" for key in missing)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.iface-backup-{timestamp}")
    shutil.copy2(path, backup)
    temporary = path.with_name(f".{path.name}.iface-tmp")
    temporary.write_text(
        "\n".join(updated_lines).rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)
    return backup
