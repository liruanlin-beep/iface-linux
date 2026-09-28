import json
import os
import subprocess
import time
import urllib.error
import urllib.request


PROVIDERS = {
    "DeepSeek": {
        "endpoint": "https://api.deepseek.com/chat/completions",
        "models": ("deepseek-v4-pro", "deepseek-v4-flash"),
        # Flash is the better default for an interactive chat window. Users
        # should not have to wait for the slower Pro reasoning path for every
        # short follow-up.
        "default_model": "deepseek-v4-flash",
    }
}


def request_json(provider, api_key, model, system_prompt, user_prompt, timeout_seconds=90):
    provider = str(provider or "DeepSeek").strip()
    definition = PROVIDERS.get(provider)
    if not definition:
        raise ValueError('iface Agent supports the DeepSeek API only.')
    api_key = str(api_key or "").strip()
    model = str(model or definition["default_model"]).strip()
    if not api_key:
        raise ValueError(f'Enter {provider} API key.')
    if not model:
        raise ValueError('Enter a model name.')

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 3000,
        "stream": False,
    }
    response = _post(definition["endpoint"], headers, payload, timeout_seconds)
    return _normalize_response(provider, response, model)


def _normalize_response(provider, response, requested_model):
    if provider != "DeepSeek":
        raise ValueError('iface Agent supports the DeepSeek API only.')
    try:
        text = response["choices"][0]["message"]["content"]
        usage = dict(response.get("usage") or {})
        return {
            "content": _extract_json(text),
            "model": str(response.get("model") or requested_model),
            "usage": usage,
        }
    except (KeyError, IndexError, StopIteration, TypeError) as exc:
        raise RuntimeError(f'{provider} response contains no valid text.') from exc


def _extract_json(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError('The AI plan is not valid JSON.') from exc


def _post(url, headers, payload, timeout_seconds):
    deadline = time.monotonic() + max(5.0, float(timeout_seconds))

    def remaining(limit=None):
        value = max(1.0, deadline - time.monotonic())
        return min(value, float(limit)) if limit is not None else value

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "User-Agent": "iface/2.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=remaining(20)) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:1500]
        raise RuntimeError(f'AI API returned HTTP {exc.code}：{detail}') from exc
    except urllib.error.URLError as exc:
        if os.name != "nt":
            raise RuntimeError(f'Cannot connect to the AI API: {exc.reason}') from exc
        # A stale Windows proxy is a common source of WinError 10061. Retry
        # directly before falling back to the system curl transport.
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=remaining(20)) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            if time.monotonic() >= deadline:
                raise RuntimeError('The DeepSeek API connection timed out. Check network and proxy settings.') from exc
            return _post_with_windows_curl(
                url, headers, payload, remaining(), timeout_seconds + 10
            )


def _post_with_windows_curl(url, headers, payload, timeout_seconds, process_timeout=None):
    command = [
        "curl.exe", "--silent", "--show-error", "--fail-with-body",
        "--noproxy", "*",
    ]
    command += ["--max-time", str(max(5, int(timeout_seconds))), url]
    for key, value in headers.items():
        command += ["-H", f"{key}: {value}"]
    command += ["--data-binary", "@-"]
    completed = subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=float(process_timeout or timeout_seconds + 10),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f'AI API request failed: {completed.stderr.strip()[:1500]}')
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('Cannot parse the AI API response.') from exc
