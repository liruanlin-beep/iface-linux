import json
from dataclasses import dataclass

from app.core.ai_provider import request_json


AGENT_TOOLS = {
    "inspect_current_context": {
        "risk": "read",
        "description": 'Read the current structure, task directory, files and connection status',
    },
    "analyze_current_results": {
        "risk": "read",
        "description": 'Analyze the current local or remote VASP results',
    },
    "set_crystal_view": {
        "risk": "view",
        "description": 'Set the structure view along crystal axis a, b or c',
    },
    "fit_structure_view": {
        "risk": "view",
        "description": 'Fit the current structure to the viewer',
    },
    "toggle_bonds": {
        "risk": "view",
        "description": 'Show or hide bonds',
    },
    "list_surface_terminations": {
        "risk": "read",
        "description": 'List available terminations of the selected Miller plane of the current structure',
    },
    "preview_surface_slab": {
        "risk": "view",
        "description": 'Preview a slab with the specified Miller indices, layers, vacuum and termination',
    },
    "generate_surface_slab": {
        "risk": "write",
        "description": 'Generate and apply a slab with the specified parameters and save it in the current task directory',
    },
    "open_high_throughput": {
        "risk": "view",
        "description": 'Open high-throughput and interface construction',
    },
    "open_task_center": {
        "risk": "view",
        "description": 'Open Task Center',
    },
    "open_post_processing": {
        "risk": "view",
        "description": 'Open PDOS and charge-difference post-processing',
    },
    "generate_input_files": {
        "risk": "write",
        "description": 'Generate VASP input files for the current structure',
    },
    "propose_incar_patch": {
        "risk": "write",
        "description": 'Apply validated permitted changes to the current INCAR',
    },
    "configure_kpoints": {
        "risk": "write",
        "description": 'Set and write the automatic KPOINTS mesh for the current task',
    },
    "start_task_queue": {
        "risk": "compute",
        "description": 'Start the automatic Slurm queue in Task Center',
    },
    "upload_current_task": {
        "risk": "write",
        "description": 'Validate the current VASP task and upload it to the selected remote directory',
    },
    "submit_remote_task": {
        "risk": "compute",
        "description": 'Submit a Slurm job in the current remote directory and record its JobID',
    },
    "query_remote_jobs": {
        "risk": "read",
        "description": 'Query Slurm job status for the current SSH user',
    },
    "download_current_results": {
        "risk": "write",
        "description": 'Download standard VASP results from the current remote directory to the local results directory',
    },
}


@dataclass
class AgentAction:
    tool: str
    arguments: dict
    reason: str
    risk: str


@dataclass
class AgentPlan:
    message: str
    actions: tuple
    warnings: tuple
    model: str
    usage: dict


def request_agent_plan(
    api_key,
    model,
    user_request,
    workspace_context,
    timeout_seconds=45,
    provider="DeepSeek",
    conversation_history=None,
):
    api_key = str(api_key or "").strip()
    if not api_key:
        raise ValueError(f'Enter {provider} API key.')
    request_text = str(user_request or "").strip()
    if not request_text:
        raise ValueError('Tell the Agent which task you want to perform.')
    tools = {
        name: {
            "description": data["description"],
            "arguments": _tool_argument_contract(name),
        }
        for name, data in AGENT_TOOLS.items()
    }
    system_prompt = (
        'You are iface Agent, a controlled assistant in VASP alloy surface and interface high-throughput software. Plan from the current workspace context and never pretend to execute actions. Use only the listed tools. Do not invent files, energies, convergence results or server status. Return every file-writing, queue-starting or compute-consuming operation as an action for user confirmation in the software. If the user explicitly asks to write, apply or save parameter suggestions to INCAR, return propose_incar_patch rather than only parameter text in message. Its changes must include only requested, system-appropriate permitted parameters. When discussing calculation types, convergence, relaxation, static calculations, DOS, bands, surfaces or interfaces and enough context is available, proactively return propose_incar_patch and/or configure_kpoints for confirmation; do not require another request to write them. Message explains; actions configure. If input generation or calculation is explicitly requested, follow parameter actions with generate_input_files and start_task_queue as appropriate. Never claim generation or execution in text alone. For a requested complete submission with SSH connected and a selected remote directory, return generate_input_files, upload_current_task and submit_remote_task in order; generation may be omitted if inputs already exist. Use query_remote_jobs for later status, download_current_results to retrieve outputs, and analyze_current_results for analysis. Opening Task Center or another window does not replace upload, submission, querying, download or analysis. Surface cutting, plane cutting, surface generation and slab requests are structure operations: with explicit parameters return preview_surface_slab or generate_surface_slab, not open_high_throughput. Use preview for a preview request and generate for generating, applying or cutting the structure. Do not change POTCAR, element order, exchange-correlation functionals, DFT+U values or van der Waals schemes. Return strict JSON: {"message":"short explanation","actions":[{"tool":"tool name","arguments":{},"reason":"reason"}],"warnings":[""]}. Actions may be empty for a question-only response.'
    )
    history = _normalize_conversation_history(conversation_history)
    user_prompt = (
        f'User request:\n{request_text}\n\nEarlier conversation in this window (chronological; context only):\n{json.dumps(history, ensure_ascii=False, indent=2)[:12000]}\n\nCurrent workspace context:\n{json.dumps(workspace_context or {}, ensure_ascii=False, indent=2)[:24000]}\n\nAvailable tools:\n{json.dumps(tools, ensure_ascii=False, indent=2)}'
    )
    response = request_json(
        provider,
        api_key,
        model,
        system_prompt,
        user_prompt,
        timeout_seconds,
    )
    raw_plan = response["content"]
    actions, validation_warnings = validate_agent_actions(raw_plan.get("actions"))
    warnings = [
        str(value)
        for value in raw_plan.get("warnings", [])
        if str(value).strip()
    ]
    warnings.extend(validation_warnings)
    return AgentPlan(
        message=str(raw_plan.get("message") or 'Agent planning complete.'),
        actions=tuple(actions),
        warnings=tuple(warnings),
        model=str(response.get("model") or model),
        usage=dict(response.get("usage") or {}),
    )


def _normalize_conversation_history(history, max_messages=20):
    normalized = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content[:4000]})
    return normalized[-max_messages:]


def validate_agent_actions(raw_actions):
    accepted = []
    warnings = []
    for raw in raw_actions or []:
        if not isinstance(raw, dict):
            warnings.append('Ignored an invalid Agent action.')
            continue
        tool = str(raw.get("tool") or "").strip()
        definition = AGENT_TOOLS.get(tool)
        if not definition:
            warnings.append(f"Blocked unknown tool: {tool or '(empty)'}。")
            continue
        arguments = raw.get("arguments") or {}
        if not isinstance(arguments, dict):
            warnings.append(f'Blocked {tool}: arguments must be an object.')
            continue
        try:
            arguments = _validate_tool_arguments(tool, arguments)
        except ValueError as exc:
            warnings.append(f'Blocked {tool}：{exc}')
            continue
        accepted.append(
            AgentAction(
                tool=tool,
                arguments=arguments,
                reason=str(raw.get("reason") or definition["description"]),
                risk=definition["risk"],
            )
        )
    return accepted, warnings


def _tool_argument_contract(tool):
    if tool in {
        "list_surface_terminations",
        "preview_surface_slab",
        "generate_surface_slab",
    }:
        return {
            "h": 'Miller h, integer',
            "k": 'Miller k, integer',
            "l": 'Miller l, integer',
            "layers": 'Atomic layers, 1-100, default 6',
            "vacuum": 'Vacuum on each side in A, 1-100, default 15',
            "fixed_layers": 'Fixed bottom layers, 0-layers, default 2',
            "termination_index": 'Termination index, nonnegative integer, default 0',
        }
    if tool == "set_crystal_view":
        return {"axis": "a|b|c"}
    if tool == "toggle_bonds":
        return {"enabled": "boolean"}
    if tool == "propose_incar_patch":
        return {
            "changes": [
                {
                    "key": 'INCAR parameter in the permitted list',
                    "new_value": 'Single-line value',
                    "reason": 'Reason for change',
                    "confidence": "0-1",
                }
            ]
        }
    if tool == "configure_kpoints":
        return {
            "mesh": ["Kx，1-99", "Ky，1-99", "Kz，1-99"],
            "mode": "Gamma|Monkhorst-Pack",
            "reason": 'Why this suits the current structure and calculation objective',
        }
    return {}


def _validate_tool_arguments(tool, arguments):
    if tool in {
        "list_surface_terminations",
        "preview_surface_slab",
        "generate_surface_slab",
    }:
        try:
            h = int(arguments.get("h", 1))
            k = int(arguments.get("k", 0))
            l = int(arguments.get("l", 0))
            layers = int(arguments.get("layers", 6))
            vacuum = float(arguments.get("vacuum", 15.0))
            fixed_layers = int(arguments.get("fixed_layers", 2))
            termination_index = int(arguments.get("termination_index", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError('Surface parameters must be valid numbers') from exc
        if (h, k, l) == (0, 0, 0):
            raise ValueError('Miller indices cannot be 0 0 0')
        if not 1 <= layers <= 100:
            raise ValueError('layers must be between 1 and 100')
        if not 1.0 <= vacuum <= 100.0:
            raise ValueError('vacuum must be between 1 and 100 A')
        if not 0 <= fixed_layers <= layers:
            raise ValueError('fixed_layers must be between 0 and layers')
        if termination_index < 0:
            raise ValueError('termination_index cannot be negative')
        return {
            "h": h,
            "k": k,
            "l": l,
            "layers": layers,
            "vacuum": vacuum,
            "fixed_layers": fixed_layers,
            "termination_index": termination_index,
            "layer_tolerance": 0.2,
        }
    if tool == "set_crystal_view":
        axis = str(arguments.get("axis") or "").lower()
        if axis not in {"a", "b", "c"}:
            raise ValueError('axis must be a, b or c')
        return {"axis": axis}
    if tool == "toggle_bonds":
        value = arguments.get("enabled")
        if not isinstance(value, bool):
            raise ValueError('enabled must be a boolean')
        return {"enabled": value}
    if tool == "propose_incar_patch":
        changes = arguments.get("changes")
        if not isinstance(changes, list) or not changes:
            raise ValueError('changes must be a nonempty array')
        return {"changes": changes[:30]}
    if tool == "configure_kpoints":
        mesh = arguments.get("mesh")
        if not isinstance(mesh, (list, tuple)) or len(mesh) != 3:
            raise ValueError('mesh must contain three integers: Kx, Ky and Kz')
        try:
            mesh = tuple(int(value) for value in mesh)
        except (TypeError, ValueError) as exc:
            raise ValueError('KPOINTS mesh dimensions must be integers') from exc
        if any(value < 1 or value > 99 for value in mesh):
            raise ValueError('KPOINTS mesh dimensions must be between 1 and 99')
        mode = str(arguments.get("mode") or "Gamma").strip()
        if mode.lower() == "gamma":
            mode = "Gamma"
        elif mode.lower() in {"monkhorst-pack", "monkhorst_pack", "mp"}:
            mode = "Monkhorst-Pack"
        else:
            raise ValueError('mode must be Gamma or Monkhorst-Pack')
        return {"mesh": mesh, "mode": mode}
    return {}
