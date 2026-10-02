import os
import re
import json
import time
import hashlib
import shutil
import subprocess
import posixpath
import urllib.parse
from pathlib import Path
from html.parser import HTMLParser

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()


# ============================================================
# CONFIGURATION
# ============================================================

GEMINI = "Gemini"
OPENROUTER = "OpenRouter"
AGENTS = [GEMINI, OPENROUTER]

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))
PROVIDER_RETRIES = int(os.getenv("PROVIDER_RETRIES", "4"))
JSON_RETRIES = int(os.getenv("JSON_RETRIES", "3"))

# If one reviewer is unreachable/unusable, continue with the other
# (a warning is printed). Set to 0 in .env for strict two-agent approval.
ALLOW_REVIEWER_FALLBACK = os.getenv("ALLOW_REVIEWER_FALLBACK", "1") == "1"

MAX_WORK_ROUNDS = 12          # was 4: long dependency chains never finished
MAX_VERIFICATION_ROUNDS = 2
MAX_FINAL_REVIEW_ROUNDS = 2

MAX_FILE_SIZE = 500_000
MAX_SNAPSHOT_CHARS = 150_000
MAX_ACTIONS = 25
MAX_FILES = 60

PROJECTS_FOLDER = Path("generated_projects")

BLOCKING = {"critical", "major"}

ALLOWED_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".md", ".txt", ".py",
    ".c", ".h", ".cpp", ".hpp", ".java", ".csv", ".svg", ".xml", ".yml",
    ".yaml", ".toml", ".ini", ".cfg", ".ts", ".jsx", ".tsx", ".sql",
}

ALLOWED_FILENAMES = {"Makefile", ".gitignore", "requirements.txt", "LICENSE",
                     "Dockerfile", "README"}
ALLOWED_DOTFILES = {".gitignore"}

_gemini_client = None
_openrouter_json_ok = True


# ============================================================
# EXCEPTIONS
# ============================================================

class TaskStopped(RuntimeError):

    def __init__(self, reason, project_root=None):
        super().__init__(reason)
        self.project_root = project_root


class ProviderError(RuntimeError):
    pass


class PermanentProviderError(ProviderError):
    pass


# ============================================================
# SMALL HELPERS
# ============================================================

def print_separator(title=None):
    print("\n" + "=" * 72)
    if title:
        print(title)
        print("=" * 72)


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def J(value):
    return json.dumps(value, indent=2, ensure_ascii=False)


def redact(value):
    text = str(value)
    for key_name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        key = os.getenv(key_name)
        if key:
            text = text.replace(key, "[REDACTED]")
    return text


def other_agent(name):
    return OPENROUTER if name == GEMINI else GEMINI


# ============================================================
# ENVIRONMENT
# ============================================================

def check_environment():
    missing = [
        name for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError("Missing from .env: " + ", ".join(missing))


def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT * 1000),
        )
    return _gemini_client


# ============================================================
# PROVIDERS
# ============================================================

def call_with_retries(provider, function):
    last_error = None

    for attempt in range(1, PROVIDER_RETRIES + 1):
        try:
            return function()
        except PermanentProviderError:
            raise
        except Exception as error:
            last_error = error
            print(f"[{provider}] attempt {attempt}/{PROVIDER_RETRIES} "
                  f"failed: {redact(error)}")
            if attempt < PROVIDER_RETRIES:
                time.sleep(min(2 ** (attempt - 1), 8))

    raise ProviderError(
        f"{provider} unavailable after {PROVIDER_RETRIES} attempts: "
        f"{redact(last_error)}"
    )


def _gemini_once(prompt, json_mode):
    config = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "32768")),
        response_mime_type="application/json" if json_mode else None,
    )

    try:
        response = get_gemini_client().models.generate_content(
            model=GEMINI_MODEL, contents=prompt, config=config
        )
    except Exception as error:
        if getattr(error, "code", None) in (400, 401, 403, 404):
            raise PermanentProviderError(str(error))
        raise

    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise RuntimeError("Gemini returned an empty response.")
    return text.strip()


def _openrouter_once(prompt):
    global _openrouter_json_ok

    response = None

    # Some models behind "openrouter/free" reject response_format.
    # On a 400, retry once without it instead of dying.
    for _ in range(2):
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        }
        if _openrouter_json_ok:
            payload["response_format"] = {"type": "json_object"}

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 400 and _openrouter_json_ok:
            _openrouter_json_ok = False
            print("[OpenRouter] model rejected JSON mode; "
                  "retrying without it.")
            continue
        break

    status = response.status_code

    if status in (408, 429) or status >= 500:
        raise RuntimeError(f"HTTP {status}: {response.text[:300]}")

    if status >= 400:
        raise PermanentProviderError(f"HTTP {status}: {response.text[:300]}")

    data = response.json()
    choices = data.get("choices") or []

    if not choices:
        raise RuntimeError(f"No choices returned: {str(data)[:300]}")

    content = (choices[0].get("message") or {}).get("content")

    if isinstance(content, list):
        content = "".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )

    if not content or not str(content).strip():
        raise RuntimeError("OpenRouter returned empty content.")

    return str(content).strip()


def ask_agent(agent_name, prompt, json_mode=False):
    if agent_name == GEMINI:
        return call_with_retries(
            GEMINI, lambda: _gemini_once(prompt, json_mode))

    if agent_name == OPENROUTER:
        return call_with_retries(
            OPENROUTER, lambda: _openrouter_once(prompt))

    raise ValueError(f"Unknown agent: {agent_name}")


# ============================================================
# JSON HANDLING
# ============================================================

def extract_json(text):
    if not text or not text.strip():
        raise ValueError("AI returned empty response.")

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text,
                       re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    for opener, closer in (("{", "}"), ("[", "]")):
        starts = [m.start() for m in re.finditer(re.escape(opener), text)][:20]

        for start in starts:
            depth = 0
            in_string = False
            escaped = False

            for i in range(start, len(text)):
                ch = text[i]

                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break

    raise ValueError("Could not extract valid JSON.")


def ask_json_agent(agent_name, prompt, purpose, validator=None):
    current_prompt = prompt
    last_error = None

    for attempt in range(JSON_RETRIES + 1):
        raw = ask_agent(agent_name, current_prompt, json_mode=True)

        try:
            result = extract_json(raw)

            if not isinstance(result, (dict, list)):
                raise ValueError("Response must be a JSON object or array.")

            if validator:
                result = validator(result)

            return result

        except Exception as error:
            last_error = error

            if attempt >= JSON_RETRIES:
                break

            print(f"[{agent_name}] response rejected ({error}). Retrying...")

            current_prompt = f"""
Your previous response for "{purpose}" was rejected.

REASON:
{error}

Return ONLY valid JSON.

Do NOT return:
- markdown
- explanations
- code fences
- any text before or after the JSON

Start directly with {{ or [.

ORIGINAL INSTRUCTION:
{prompt}
"""

    raise TaskStopped(
        f"{agent_name} could not return a valid response for "
        f"'{purpose}'. Last error: {last_error}"
    )


def dict_validator(**required):

    def validate(result):
        if not isinstance(result, dict):
            raise ValueError("Top-level JSON must be an object.")

        for key, expected_type in required.items():
            if key not in result:
                raise ValueError(f"Missing required field '{key}'.")
            if not isinstance(result[key], expected_type):
                raise ValueError(
                    f"Field '{key}' must be {expected_type.__name__}.")

        return result

    return validate


# ============================================================
# SAFE PATHS
# ============================================================

def safe_relative_path(raw):
    path = clean(raw).replace("\\", "/")

    if not path:
        raise ValueError("Empty file path.")
    if "\x00" in path:
        raise ValueError("Null byte in path.")
    if len(path) > 200:
        raise ValueError("File path is too long.")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"Absolute paths are not allowed: {path}")

    parts = [x for x in path.split("/") if x not in ("", ".")]

    if not parts:
        raise ValueError("Empty file path.")
    if len(parts) > 8:
        raise ValueError(f"Path too deep: {path}")

    for part in parts:
        if part == "..":
            raise ValueError("Path traversal is not allowed.")

        if part.startswith(".") and part not in ALLOWED_DOTFILES:
            raise ValueError(f"Hidden file not allowed: {path}")

        if len(part) > 100 or re.search(r'[<>:"|?*\x00-\x1f]', part):
            raise ValueError(f"Invalid characters in path: {path}")

    return "/".join(parts)


def project_file(project_root, relative_path):
    relative_path = safe_relative_path(relative_path)
    root = project_root.resolve()
    target = (root / relative_path).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("File escapes project directory.")

    current = root
    for part in relative_path.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlinks are not allowed.")

    return target


def check_extension(relative_path):
    name = relative_path.split("/")[-1]

    if name in ALLOWED_FILENAMES:
        return

    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type not allowed: {relative_path}")


def safe_project_name(name):
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", clean(name))
    name = name.strip("._-")
    return (name or "ai_team_project")[:80]


def create_project_workspace(project_name):
    PROJECTS_FOLDER.mkdir(parents=True, exist_ok=True)

    base = safe_project_name(project_name)
    candidate = PROJECTS_FOLDER / base
    counter = 1

    while True:
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            counter += 1
            candidate = PROJECTS_FOLDER / f"{base}_{counter}"


# ============================================================
# PROJECT FILES
# ============================================================

def list_project_files(project_root):
    result = []

    for directory, directories, filenames in os.walk(
            project_root, followlinks=False):

        directories[:] = sorted(
            d for d in directories
            if d not in {"__pycache__", "node_modules", ".git"}
            and not os.path.islink(os.path.join(directory, d))
        )

        for filename in sorted(filenames):
            full_path = Path(directory) / filename
            if full_path.is_file() and not full_path.is_symlink():
                result.append(
                    full_path.relative_to(project_root).as_posix())

    return sorted(result)


def read_project_file(project_root, relative_path):
    target = project_file(project_root, relative_path)

    if not target.is_file():
        return None

    return target.read_text(encoding="utf-8", errors="replace")


def create_project_snapshot(project_root):
    project_files = list_project_files(project_root)

    if not project_files:
        return "[PROJECT IS EMPTY]"

    blocks = []
    total = 0

    for relative_path in project_files:
        content = read_project_file(project_root, relative_path) or ""

        block = (f"\n===== FILE: {relative_path} =====\n"
                 f"{content}\n"
                 f"===== END FILE: {relative_path} =====\n")

        total += len(block)

        if total > MAX_SNAPSHOT_CHARS:
            raise TaskStopped(
                "Project is too large to verify safely.", project_root)

        blocks.append(block)

    return "".join(blocks)


def snapshot_hash(snapshot):
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:12]


def ownership_text(file_owner):
    if not file_owner:
        return "(no files written yet)"

    return "\n".join(
        f"- {path}: last written by {agent}"
        for path, agent in sorted(file_owner.items())
    )


# ============================================================
# FILE ACTION SYSTEM
# ============================================================

ACTION_ALIASES = {
    "write": {"write", "write_file", "create", "create_file", "new_file",
              "save", "save_file", "overwrite", "overwrite_file",
              "add_file", "make_file"},
    "edit": {"edit", "edit_file", "modify", "modify_file", "update",
             "update_file", "patch", "patch_file", "replace",
             "replace_in_file", "str_replace", "append_file"},
    "delete": {"delete", "delete_file", "remove", "remove_file"},
    "read": {"read", "read_file", "view", "view_file", "open_file",
             "inspect", "inspect_file", "list_files"},
}


def normalize_action_name(name):
    key = clean(name).lower().replace("-", "_").replace(" ", "_")

    for canonical, aliases in ACTION_ALIASES.items():
        if key in aliases:
            return canonical

    return None


def first_value(data, keys):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def plan_file_ops(project_root, actions, agent_name, file_owner,
                  allowed_paths):

    if not isinstance(actions, list):
        raise ValueError("'actions' must be a list.")

    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"Too many actions. Maximum: {MAX_ACTIONS}.")

    disk_files = set(list_project_files(project_root))
    virtual = {}

    def current_content(path):
        if path in virtual:
            return virtual[path]
        if path in disk_files:
            return read_project_file(project_root, path)
        return None

    for number, raw in enumerate(actions, start=1):
        label = f"Action #{number}"

        if not isinstance(raw, dict):
            raise ValueError(f"{label} must be an object.")

        action_name = first_value(
            raw, ("action", "type", "op", "operation"))
        kind = normalize_action_name(action_name)

        if kind is None:
            raise ValueError(
                f"{label}: unsupported action '{action_name}'. "
                f"Use write, edit or delete.")

        # The full snapshot is already in the prompt; reads are no-ops.
        if kind == "read":
            continue

        path = safe_relative_path(
            first_value(raw, ("path", "file", "filename", "file_path")))

        check_extension(path)

        if path not in allowed_paths:
            raise ValueError(
                f"{label}: '{path}' is outside your assigned "
                f"allowed_files scope. Allowed: {sorted(allowed_paths)}")

        current = current_content(path)
        exists = current is not None
        reason = clean(raw.get("reason"))

        # NOTE: editing a teammate-owned file no longer requires a
        # "reason". allowed_files already authorizes it, and weak
        # models kept failing on this formality.

        if kind == "delete":
            if not reason:
                raise ValueError(
                    f"{label}: delete requires a non-empty reason.")
            virtual[path] = None
            continue

        content = first_value(
            raw, ("content", "new_content", "contents"))

        if kind == "edit" and content is None:
            if not exists:
                raise ValueError(
                    f"{label}: cannot edit '{path}' because it does not "
                    f"exist. Use a write action with the full content.")

            edits = raw.get("edits")
            if edits is None:
                edits = [raw]

            if not isinstance(edits, list) or not edits:
                raise ValueError(
                    f"{label}: 'edits' must be a non-empty list.")

            text = current

            for edit in edits:
                if not isinstance(edit, dict):
                    raise ValueError(
                        f"{label}: each edit must be an object.")

                old_text = first_value(
                    edit, ("old_text", "old", "search", "find"))
                new_text = first_value(
                    edit, ("new_text", "new", "replace", "replacement"))

                if (not isinstance(old_text, str) or not old_text
                        or not isinstance(new_text, str)):
                    raise ValueError(
                        f"{label}: edit requires string 'old_text' "
                        f"and string 'new_text'.")

                count = text.count(old_text)

                if count == 0:
                    raise ValueError(
                        f"{label}: old_text was not found in '{path}'. "
                        f"Do NOT use edit. Instead use a write action "
                        f"with the COMPLETE new content of '{path}'.")

                if count > 1 and not edit.get("replace_all"):
                    raise ValueError(
                        f"{label}: old_text appears {count} times in "
                        f"'{path}'. Use a write action with the complete "
                        f"file content instead.")

                text = text.replace(old_text, new_text)

            content = text

        if not isinstance(content, str):
            raise ValueError(f"{label}: '{path}' requires string content.")

        if len(content.encode("utf-8")) > MAX_FILE_SIZE:
            raise ValueError(f"{label}: '{path}' is too large.")

        virtual[path] = content

    operations = []

    for path, content in virtual.items():
        before = (read_project_file(project_root, path)
                  if path in disk_files else None)

        if content != before:
            operations.append((path, content))

    final_files = (
        disk_files | {p for p, c in virtual.items() if c is not None}
    ) - {p for p, c in virtual.items() if c is None}

    if len(final_files) > MAX_FILES:
        raise ValueError(f"Too many files. Maximum: {MAX_FILES}.")

    return operations


def commit_file_ops(project_root, operations, agent_name, file_owner):
    changed = []

    for path, content in operations:
        target = project_file(project_root, path)

        if content is None:
            if target.is_file():
                target.unlink()
                file_owner.pop(path, None)
                changed.append(path)
                print(f"  [{agent_name}] DELETED: {path}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)

        temp = target.with_name(target.name + ".tmp")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, target)

        file_owner[path] = agent_name
        changed.append(path)
        print(f"  [{agent_name}] WROTE: {path}")

    if not operations:
        print(f"  [{agent_name}] no file changes")

    return changed


def action_validator(project_root, agent_name, file_owner, allowed_paths):

    def validate(result):
        result = dict_validator(actions=list)(result)
        result["_ops"] = plan_file_ops(
            project_root, result["actions"], agent_name,
            file_owner, allowed_paths)
        return result

    return validate


ACTION_FORMAT = """
FILE ACTIONS (inside the "actions" list):

1. WRITE  (PREFERRED - always use this for new files and for any
   file smaller than about 20000 characters; give the COMPLETE file)
{
  "action": "write",
  "path": "script.js",
  "content": "complete file content"
}

2. EDIT   (only for very large files; old_text must match EXACTLY)
{
  "action": "edit",
  "path": "script.js",
  "edits": [
    {"old_text": "exact text currently in the file",
     "new_text": "replacement text"}
  ]
}

3. DELETE
{
  "action": "delete",
  "path": "old.txt",
  "reason": "Why this file must be removed"
}

IMPORTANT:

- Only touch files inside your assigned allowed_files.
- You MAY modify files a teammate created if they are in your
  allowed_files. No special reason is needed.
- When changing an existing file, prefer WRITE with the complete
  updated content over EDIT. It is far less error-prone.
- Do not add unnecessary features.
- Do not execute shell commands.
"""


# ============================================================
# TASK UNDERSTANDING
# ============================================================

def understand_task(agent_name, user_task):
    prompt = f"""
You are {agent_name}, one of TWO EQUAL AI TEAMMATES.

TASK MODE.

USER REQUEST:
{user_task}

Independently understand exactly what the user wants.

Do not invent requirements.
Do not add unnecessary features.

Return ONLY JSON:

{{
  "task_summary": "...",
  "goal": "...",
  "deliverable": "...",
  "requirements": [],
  "constraints": [],
  "success_criteria": [],
  "risks": []
}}
"""

    return ask_json_agent(
        agent_name, prompt, "independent task understanding",
        dict_validator(task_summary=str, requirements=list))


def compare_understandings(user_task, understandings):
    prompt = f"""
You are {OPENROUTER}, an equal AI teammate.

USER TASK:
{user_task}

GEMINI UNDERSTANDING:
{J(understandings[GEMINI])}

OPENROUTER UNDERSTANDING:
{J(understandings[OPENROUTER])}

Compare both understandings.

Do NOT choose a winner.

Identify:

- shared requirements
- meaningful differences
- missing points
- unsupported assumptions
- resolved requirements
- resolved success criteria

Return ONLY JSON:

{{
  "shared_understanding": [],
  "differences": [],
  "missing_points": [],
  "unsafe_assumptions": [],
  "resolved_requirements": [],
  "resolved_success_criteria": []
}}
"""

    return ask_json_agent(
        OPENROUTER, prompt, "understanding comparison",
        dict_validator(resolved_requirements=list))


# ============================================================
# PLANNING
# ============================================================

PLAN_TEMPLATE = """
{
  "project_name": "...",
  "project_type": "...",
  "goal": "...",
  "subtasks": [
    {
      "id": "T1",
      "title": "...",
      "description": "...",
      "dependencies": [],
      "suggested_owner": "Gemini or OpenRouter",
      "allowed_files": [],
      "acceptance_criteria": []
    }
  ],
  "global_success_criteria": [],
  "testing_strategy": []
}
"""


def create_consensus_plan(user_task, understandings, comparison):
    base = f"""
USER TASK:
{user_task}

GEMINI UNDERSTANDING:
{J(understandings[GEMINI])}

OPENROUTER UNDERSTANDING:
{J(understandings[OPENROUTER])}

COMPARISON:
{J(comparison)}
"""

    plans = {}

    for agent in AGENTS:
        print(f"{agent} is planning...")

        prompt = f"""
You are an equal AI TEAM teammate.

Create a practical implementation plan.

{base}

Rules:

- preserve important requirements
- add no unnecessary features
- keep the plan SHORT: at most 6 subtasks, and avoid long
  dependency chains (prefer subtasks that can run in parallel)
- do NOT create documentation-only, wireframe or test-report
  subtasks; every subtask must produce real project files
- assign work based on actual work
- both agents should contribute genuinely

VERY IMPORTANT:

Every subtask MUST contain "allowed_files": [] listing the project
files that the subtask is expected to create or modify.

Return ONLY JSON:

{PLAN_TEMPLATE}
"""

        plans[agent] = ask_json_agent(
            agent, prompt, f"{agent} task planning",
            dict_validator(subtasks=list))

    merge_prompt = f"""
You are Gemini, an equal AI TEAM teammate.

Two independent plans were created.

{base}

GEMINI PLAN:
{J(plans[GEMINI])}

OPENROUTER PLAN:
{J(plans[OPENROUTER])}

Create ONE consensus plan.

Do not favor either agent.

Keep: necessary requirements, useful subtasks, correct dependencies,
sensible assignments, correct allowed file scopes.

Remove: duplicates, unsupported assumptions, unnecessary work,
documentation-only / wireframe / test-report subtasks.

Keep it SHORT (at most 6 subtasks) with shallow dependencies.

IMPORTANT:

Every subtask MUST contain "allowed_files": [] listing the relative
files that this subtask is genuinely expected to create or modify.

Return ONLY JSON:

{PLAN_TEMPLATE}
"""

    print("Gemini is merging both plans...")

    return ask_json_agent(
        GEMINI, merge_prompt, "consensus plan",
        dict_validator(subtasks=list))


def normalize_plan(plan):
    if not isinstance(plan, dict):
        raise TaskStopped("Invalid consensus plan.")

    tasks = []
    seen = set()

    for index, task in enumerate(plan.get("subtasks", []), start=1):
        if not isinstance(task, dict):
            continue

        task_id = clean(task.get("id")) or f"T{index}"
        while task_id in seen:
            task_id += "_x"
        seen.add(task_id)

        owner = clean(task.get("suggested_owner") or task.get("owner"))
        if owner not in AGENTS:
            owner = AGENTS[(index - 1) % 2]

        dependencies = task.get("dependencies")
        if not isinstance(dependencies, list):
            dependencies = []

        allowed_files = task.get("allowed_files")
        if not isinstance(allowed_files, list):
            allowed_files = []

        normalized_files = []
        for raw_path in allowed_files:
            try:
                path = safe_relative_path(raw_path)
                check_extension(path)
                if path not in normalized_files:
                    normalized_files.append(path)
            except ValueError:
                continue

        criteria = task.get("acceptance_criteria")

        tasks.append({
            "id": task_id,
            "title": clean(task.get("title")) or f"Subtask {index}",
            "description": clean(task.get("description")),
            "dependencies": [clean(x) for x in dependencies],
            "owner": owner,
            "allowed_files": normalized_files,
            "acceptance_criteria":
                criteria if isinstance(criteria, list) else [],
        })

    if not tasks:
        raise TaskStopped("Consensus plan contains no usable subtasks.")

    ids = {task["id"] for task in tasks}

    for task in tasks:
        task["dependencies"] = [
            d for d in task["dependencies"]
            if d in ids and d != task["id"]
        ]

    plan["subtasks"] = tasks
    plan["project_name"] = (
        clean(plan.get("project_name")) or "ai_team_project")

    return plan


def display_plan(plan):
    print_separator("CONSENSUS TASK PLAN")

    print(f"Project: {plan.get('project_name', '')}")
    print(f"Type:    {plan.get('project_type', '')}")
    print(f"Goal:    {plan.get('goal', '')}\n")

    for task in plan["subtasks"]:
        dependencies = ",".join(task["dependencies"]) or "-"
        allowed = ", ".join(task["allowed_files"]) or "(none)"

        print(f"  [{task['id']}] {task['title']} -> {task['owner']} "
              f"(deps: {dependencies})")
        print(f"       allowed files: {allowed}")


# ============================================================
# AGENT IMPLEMENTATION (with teammate failover)
# ============================================================

def run_agent_work(agent_name, user_task, plan, assigned, project_root,
                   file_owner, feedback):

    snapshot = create_project_snapshot(project_root)

    allowed_paths = {
        path for task in assigned for path in task.get("allowed_files", [])
    }

    # A subtask with no usable allowed_files could never write anything.
    # Fall back to every file named anywhere in the plan.
    if not allowed_paths:
        allowed_paths = {
            path for task in plan["subtasks"]
            for path in task.get("allowed_files", [])
        }

    def build_prompt(agent):
        return f"""
You are {agent}, an EQUAL AI TEAMMATE building a real project.

USER TASK:
{user_task}

CONSENSUS PLAN:
{J(plan)}

YOUR ASSIGNED SUBTASKS:
{J(assigned)}

YOUR ALLOWED FILES:
{J(sorted(allowed_paths))}

FILE OWNERSHIP:
{ownership_text(file_owner)}

CURRENT PROJECT:
{snapshot}

NOTES FROM EARLIER ROUNDS:
{J(feedback)}

RULES:

1. Inspect the current project snapshot.
2. Preserve correct work.
3. Implement only your assigned subtasks.
4. You may modify teammate-created files that are inside your
   allowed files, when your subtask needs it.
5. When changing an existing file, WRITE the complete updated file
   (preferred) instead of using small edits.
6. Do not add unnecessary features.
7. Do not execute shell commands.

{ACTION_FORMAT}

Return ONLY JSON:

{{
  "summary": "...",
  "completed_subtasks": [],
  "actions": [],
  "known_risks": []
}}
"""

    last_error = None

    for agent in (agent_name, other_agent(agent_name)):
        try:
            result = ask_json_agent(
                agent, build_prompt(agent),
                f"{agent} implementation work",
                action_validator(project_root, agent, file_owner,
                                 allowed_paths))

            changed = commit_file_ops(
                project_root, result["_ops"], agent, file_owner)

            return result, changed

        except (TaskStopped, ProviderError) as error:
            last_error = error
            print(f"[{agent}] could not finish this work "
                  f"({redact(error)})")

            if agent == agent_name:
                print(f"Handing it to {other_agent(agent_name)}...")

    raise TaskStopped(
        f"Neither agent could complete the assigned subtasks. "
        f"Last error: {last_error}")


# ============================================================
# LOCAL VERIFICATION
# ============================================================

class HTMLScan(HTMLParser):

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    OPTIONAL_END_TAGS = {"p", "li", "dt", "dd", "tr", "td", "th", "thead",
                         "tbody", "tfoot", "option", "optgroup", "colgroup",
                         "caption", "html", "head", "body"}

    REF_TAGS = {"script", "link", "img", "a", "source", "audio", "video",
                "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = set()
        self.refs = []
        self.stack = []
        self.mismatch = []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        attributes = dict(attrs)

        if tag in self.REF_TAGS:
            for attribute in ("src", "href"):
                value = attributes.get(attribute)
                if value:
                    self.refs.append((tag, value))

        if tag not in self.VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID_TAGS:
            return

        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.mismatch.append(self.stack.pop())
            if self.stack:
                self.stack.pop()
        else:
            self.mismatch.append("/" + tag)


def local_verification(project_root):
    print_separator("LOCAL PROJECT VERIFICATION")

    issues = []

    def add(severity, category, path, issue, fix=""):
        issues.append({
            "severity": severity,
            "category": category,
            "path": path,
            "issue": issue,
            "evidence": "local check",
            "recommended_fix": fix,
            "owner": None,
            "source": "local",
        })

    project_files = list_project_files(project_root)

    if not project_files:
        add("critical", "structure", "", "Project workspace is empty.",
            "Create project files.")
        return issues

    file_set = set(project_files)
    node = shutil.which("node")

    for relative_path in project_files:
        text = read_project_file(project_root, relative_path) or ""
        extension = Path(relative_path).suffix.lower()

        if not text.strip():
            add("major", "structure", relative_path, "File is empty.")
            continue

        if extension == ".py":
            try:
                compile(text, relative_path, "exec")
            except SyntaxError as error:
                add("major", "python", relative_path,
                    f"Python syntax error: {error}")

        elif extension == ".json":
            try:
                json.loads(text)
            except ValueError as error:
                add("major", "json", relative_path, f"Invalid JSON: {error}")

        elif extension == ".css":
            if text.count("{") != text.count("}"):
                add("major", "css", relative_path, "Unbalanced CSS braces.")

        elif extension in (".js", ".mjs"):
            if node:
                try:
                    result = subprocess.run(
                        [node, "--check",
                         str(project_file(project_root, relative_path))],
                        capture_output=True, text=True, timeout=20)

                    if result.returncode != 0:
                        add("major", "javascript", relative_path,
                            "JavaScript syntax error.", result.stderr[:500])

                except Exception as error:
                    add("minor", "javascript", relative_path,
                        f"JS check failed: {error}")

        elif extension in (".html", ".htm"):
            scanner = HTMLScan()

            try:
                scanner.feed(text)
                scanner.close()
            except Exception as error:
                add("major", "html", relative_path,
                    f"HTML parse failed: {error}")
                continue

            lower = text.lower()

            if "html" not in scanner.tags:
                add("major", "html", relative_path, "Missing <html> element.")

            if "body" not in scanner.tags:
                add("major", "html", relative_path, "Missing <body> element.")

            if "<!doctype" not in lower[:300]:
                add("minor", "html", relative_path,
                    "Missing <!DOCTYPE html>.")

            if "title" not in scanner.tags:
                add("minor", "html", relative_path, "Missing <title>.")

            bad_tags = [
                tag for tag in (scanner.mismatch + scanner.stack)
                if tag.lstrip("/") not in scanner.OPTIONAL_END_TAGS
            ]

            if bad_tags:
                add("major", "html", relative_path,
                    "Unbalanced/unclosed tags: " + ", ".join(bad_tags[:5]))

            for tag, reference in scanner.refs:
                if not isinstance(reference, str):
                    continue

                if re.match(
                        r"^(https?:|//|data:|mailto:|tel:|javascript:|#)",
                        reference, re.IGNORECASE):
                    continue

                reference_path = urllib.parse.unquote(
                    re.split(r"[?#]", reference)[0])

                if reference_path.startswith("/"):
                    resolved = posixpath.normpath(reference_path.lstrip("/"))
                else:
                    resolved = posixpath.normpath(posixpath.join(
                        posixpath.dirname(relative_path), reference_path))

                if resolved.startswith("..") or resolved not in file_set:
                    add("major", "html", relative_path,
                        f"<{tag}> references missing local file "
                        f"'{reference}'.")

    if (any(p.lower().endswith((".js", ".mjs")) for p in project_files)
            and not node):
        print("Note: Node.js not found; JavaScript syntax was not "
              "checked locally.")

    if issues:
        print(f"Local verification found {len(issues)} issue(s).")
    else:
        print("Local verification passed.")

    return issues


# ============================================================
# ISSUE HANDLING
# ============================================================

def normalize_issue(issue, source=""):
    if not isinstance(issue, dict):
        return None

    severity = clean(issue.get("severity")).lower()
    if severity not in {"critical", "major", "minor"}:
        severity = "minor"

    text = clean(issue.get("issue"))
    if not text:
        return None

    # Normalize the path so "./script.js" matches file ownership/scope.
    path = clean(issue.get("path")).replace("\\", "/")
    if path:
        try:
            path = safe_relative_path(path)
        except ValueError:
            pass

    return {
        "severity": severity,
        "category": clean(issue.get("category")),
        "path": path,
        "issue": text,
        "evidence": clean(issue.get("evidence")),
        "recommended_fix": clean(issue.get("recommended_fix")),
        "owner": None,
        "source": source or clean(issue.get("source")),
    }


def issue_key(issue):
    words = re.sub(r"\W+", " ", issue["issue"].lower()).strip()[:100]
    return (issue["path"].lower(), words)


def combine_issues(sources):
    merged = {}
    severity_order = {"critical": 0, "major": 1, "minor": 2}

    for source, raw_list in sources.items():
        for raw_issue in raw_list:
            issue = normalize_issue(raw_issue, source)
            if issue:
                merged.setdefault(issue_key(issue), issue)

    return sorted(merged.values(),
                  key=lambda i: severity_order[i["severity"]])


def blocking_issues(issues):
    return [i for i in issues if i["severity"] in BLOCKING]


def assign_issue_owners(issues, file_owner):
    load = {agent: 0 for agent in AGENTS}
    unassigned = []

    for issue in issues:
        owner = file_owner.get(issue["path"])

        if owner in AGENTS:
            issue["owner"] = owner
            load[owner] += 1
        else:
            unassigned.append(issue)

    for issue in unassigned:
        owner = min(AGENTS, key=lambda a: load[a])
        issue["owner"] = owner
        load[owner] += 1

    return issues


# ============================================================
# FIX ISSUES (with teammate failover)
# ============================================================

def fix_issues(agent_name, user_task, plan, issues, project_root,
               file_owner):

    owned_issues = [i for i in issues if i.get("owner") == agent_name]

    if not owned_issues:
        return []

    print_separator(f"{agent_name} FIXING ASSIGNED ISSUES")

    # Issues often span files (e.g. HTML calls a missing JS function),
    # so the fixer may touch any existing file plus the issue paths.
    allowed_paths = set(list_project_files(project_root))
    allowed_paths |= {i["path"] for i in owned_issues if i["path"]}

    snapshot = create_project_snapshot(project_root)

    def build_prompt(agent):
        return f"""
You are {agent}, an equal AI teammate.

Fix ONLY the assigned genuine issues.

USER TASK:
{user_task}

PLAN:
{J(plan)}

ISSUES TO FIX:
{J(owned_issues)}

FILE OWNERSHIP:
{ownership_text(file_owner)}

CURRENT PROJECT:
{snapshot}

Rules:

- Fix the real cause.
- Keep changes small in effect, but when changing a file prefer WRITE
  with the COMPLETE updated file content instead of EDIT.
- Preserve correct work.
- Do not add new features.

{ACTION_FORMAT}

Return ONLY JSON:

{{
  "summary": "...",
  "completed_issues": [],
  "actions": []
}}
"""

    last_error = None

    for agent in (agent_name, other_agent(agent_name)):
        try:
            result = ask_json_agent(
                agent, build_prompt(agent), f"{agent} issue fixing",
                action_validator(project_root, agent, file_owner,
                                 allowed_paths))

            return commit_file_ops(
                project_root, result["_ops"], agent, file_owner)

        except (TaskStopped, ProviderError) as error:
            last_error = error
            print(f"[{agent}] could not fix the issues "
                  f"({redact(error)})")

    print(f"Fix attempt failed for {agent_name}'s issues: "
          f"{redact(last_error)}")
    return []


def run_fix_phase(user_task, plan, issues, project_root, file_owner,
                  round_number):

    assign_issue_owners(issues, file_owner)

    for issue in issues:
        print(f"  [{issue['severity'].upper()}] {issue['path'] or '-'}: "
              f"{issue['issue']} -> {issue['owner']}")

    order = AGENTS if round_number % 2 else list(reversed(AGENTS))

    for agent in order:
        fix_issues(agent, user_task, plan, issues, project_root, file_owner)


# ============================================================
# AI REVIEW
# ============================================================

def review_validator():

    def validate(result):
        if not isinstance(result, dict):
            raise ValueError("Top-level JSON must be an object.")

        if not isinstance(result.get("approved"), bool):
            raise ValueError("'approved' must be true or false.")

        if not isinstance(result.get("issues"), list):
            raise ValueError("'issues' must be a list.")

        result["issues"] = [
            issue for issue in (normalize_issue(x) for x in result["issues"])
            if issue
        ]

        if not result["approved"] and not result["issues"]:
            raise ValueError(
                "Rejected project must contain concrete issues.")

        return result

    return validate


def cross_verify(agent_name, user_task, plan, snapshot, file_owner):
    prompt = f"""
You are {agent_name}, an equal AI teammate reviewing the ACTUAL project.

USER TASK:
{user_task}

PLAN:
{J(plan)}

FILE OWNERSHIP:
{ownership_text(file_owner)}

CURRENT PROJECT:
{snapshot}

Ask: "What is genuinely STILL WRONG?"

Check: user requirements, correctness, missing functionality, broken
references, obvious bugs, integration, unnecessary extras.

Only report genuine problems. Do not invent issues.
Minor polish is optional and must NOT block approval.

Return ONLY JSON:

{{
  "approved": true,
  "summary": "...",
  "issues": [
    {{
      "severity": "critical|major|minor",
      "category": "...",
      "path": "...",
      "issue": "...",
      "evidence": "...",
      "recommended_fix": "..."
    }}
  ]
}}
"""

    return ask_json_agent(
        agent_name, prompt, f"{agent_name} project verification",
        review_validator())


def final_review(agent_name, user_task, plan, snapshot):
    prompt = f"""
You are {agent_name}, an equal AI teammate.

This is the FINAL REVIEW.

The other teammate is reviewing the exact same project snapshot.

USER TASK:
{user_task}

PLAN:
{J(plan)}

FINAL PROJECT:
{snapshot}

Approve ONLY if:

- the user's request is satisfied
- important requirements are present
- no critical problem remains
- no major problem remains
- files are coherent
- project is usable
- project is not padded with useless functionality

Minor polish does not block approval.

If a genuine major or critical problem remains, reject and list it.

Return ONLY JSON:

{{
  "approved": true,
  "summary": "...",
  "issues": []
}}
"""

    return ask_json_agent(
        agent_name, prompt, f"{agent_name} final approval",
        review_validator())


def safe_review(function, agent, *args):
    """Run a review; if this reviewer is unusable, optionally continue
    with the other reviewer instead of killing the whole run."""
    try:
        return function(agent, *args)
    except (TaskStopped, ProviderError) as error:
        if not ALLOW_REVIEWER_FALLBACK:
            raise
        print(f"WARNING: {agent} could not review ({redact(error)}). "
              f"Continuing with the other reviewer only.")
        return {"approved": True, "summary": "reviewer unavailable",
                "issues": [], "skipped": True}


def ensure_some_review(reviews):
    if all(r.get("skipped") for r in reviews.values()):
        raise TaskStopped("Neither agent could review the project.")


# ============================================================
# MAIN BUILD WORKFLOW
# ============================================================

def build_and_release(user_task, plan, project_root):
    file_owner = {}
    completed = set()
    feedback = []

    # ---------------- WORK ----------------

    for work_round in range(1, MAX_WORK_ROUNDS + 1):
        ready = [
            task for task in plan["subtasks"]
            if task["id"] not in completed
            and all(d in completed for d in task["dependencies"])
        ]

        if not ready:
            break

        print_separator(f"WORK ROUND {work_round}")

        order = AGENTS if work_round % 2 else list(reversed(AGENTS))

        for agent in order:
            assigned = [t for t in ready if t["owner"] == agent]

            if not assigned:
                continue

            print(f"{agent} is working on: "
                  + ", ".join(t["id"] for t in assigned))

            result, changed = run_agent_work(
                agent, user_task, plan, assigned, project_root,
                file_owner, feedback)

            assigned_ids = {t["id"] for t in assigned}

            reported = {
                clean(v) for v in result.get("completed_subtasks", [])
                if isinstance(v, str)
            }
            reported &= assigned_ids

            if not reported and changed:
                reported = assigned_ids

            completed |= reported

            leftover = assigned_ids - reported
            if leftover:
                feedback.append(
                    f"{agent} did not complete: {sorted(leftover)}")

    unfinished = [t["id"] for t in plan["subtasks"]
                  if t["id"] not in completed]

    if unfinished:
        print(f"\nWARNING: subtasks not completed: {unfinished}. "
              f"Reviewers will check what is missing.")
        feedback.append(f"Unfinished subtasks: {unfinished}")

    # ---------------- VERIFICATION ----------------

    verified = False

    for verification_round in range(1, MAX_VERIFICATION_ROUNDS + 1):
        print_separator(f"VERIFICATION ROUND {verification_round}")

        local_issues = local_verification(project_root)
        current_snapshot = create_project_snapshot(project_root)

        reviews = {}

        for agent in AGENTS:
            print(f"{agent} is reviewing the project...")
            reviews[agent] = safe_review(
                cross_verify, agent, user_task, plan,
                current_snapshot, file_owner)

        ensure_some_review(reviews)

        issues = combine_issues({
            "local": local_issues,
            "Gemini review": reviews[GEMINI]["issues"],
            "OpenRouter review": reviews[OPENROUTER]["issues"],
        })

        blockers = blocking_issues(issues)

        for issue in issues:
            if issue not in blockers:
                print(f"  (minor, not blocking) {issue['path']}: "
                      f"{issue['issue']}")

        if not blockers:
            print("\nNo critical/major issues remain.")
            verified = True
            break

        print(f"Blocking issues: {len(blockers)}")

        if verification_round == MAX_VERIFICATION_ROUNDS:
            break

        run_fix_phase(user_task, plan, blockers, project_root,
                      file_owner, verification_round)

        feedback = ["Previously reported issues: " + J(blockers)]

    if not verified:
        raise TaskStopped(
            "Verification did not reach a clean state within "
            f"{MAX_VERIFICATION_ROUNDS} rounds. Project NOT released.",
            project_root)

    # ---------------- FINAL MUTUAL APPROVAL ----------------

    approved = False
    reviewed_hash = None

    for final_round in range(1, MAX_FINAL_REVIEW_ROUNDS + 1):
        print_separator(f"FINAL MUTUAL APPROVAL (round {final_round})")

        local_issues = local_verification(project_root)
        current_snapshot = create_project_snapshot(project_root)
        reviewed_hash = snapshot_hash(current_snapshot)

        print(f"Both agents review the SAME snapshot "
              f"(hash {reviewed_hash}).")

        final_reviews = {}

        for agent in AGENTS:
            final_reviews[agent] = safe_review(
                final_review, agent, user_task, plan, current_snapshot)

        ensure_some_review(final_reviews)

        verdicts = {}

        for agent, review in final_reviews.items():
            # Only genuine critical/major issues block. A rejection that
            # lists minor issues only is treated as approval (otherwise
            # the loop could never converge).
            verdicts[agent] = not blocking_issues(review["issues"])

            label = ("SKIPPED" if review.get("skipped")
                     else "APPROVED" if verdicts[agent] else "REJECTED")
            print(f"{agent}: {label}")

        local_blockers = blocking_issues(local_issues)

        if all(verdicts.values()) and not local_blockers:
            approved = True
            break

        if final_round == MAX_FINAL_REVIEW_ROUNDS:
            break

        issues = combine_issues({
            "local": local_issues,
            "Gemini final": final_reviews[GEMINI]["issues"],
            "OpenRouter final": final_reviews[OPENROUTER]["issues"],
        })

        blockers = blocking_issues(issues)

        if blockers:
            run_fix_phase(user_task, plan, blockers, project_root,
                          file_owner, final_round)

    if not approved:
        raise TaskStopped(
            "Both agents did not approve the final project. "
            "Project NOT released.", project_root)

    # ---------------- RELEASE GATE ----------------

    current_hash = snapshot_hash(create_project_snapshot(project_root))

    if current_hash != reviewed_hash:
        raise TaskStopped(
            "Project changed after final approval. Project NOT released.",
            project_root)

    if blocking_issues(local_verification(project_root)):
        raise TaskStopped(
            "Final local verification failed. Project NOT released.",
            project_root)

    # ---------------- SUCCESS ----------------

    print_separator("AI TEAM TASK COMPLETED")
    print("Both AI teammates approved the exact same final project state.")
    print(f"Approved snapshot hash: {reviewed_hash}")
    print("Final local verification passed.")
    print(f"\nProject location:\n{project_root.resolve()}\n\nFiles:")

    for name in list_project_files(project_root):
        print(f"  - {name}")

    return project_root


# ============================================================
# EXECUTE TASK
# ============================================================

def execute_task(user_task):
    check_environment()

    print_separator("AI TEAM TASK MODE")
    print("Both AI teammates will independently understand "
          "and work on the task.")

    print_separator("STEP 1 - INDEPENDENT TASK UNDERSTANDING")

    understandings = {}

    for agent in AGENTS:
        print(f"{agent} is understanding the task...")
        understandings[agent] = understand_task(agent, user_task)

    print_separator("COMPARING BOTH AGENTS' UNDERSTANDING")

    comparison = compare_understandings(user_task, understandings)

    print_separator("CREATING COLLABORATIVE TASK PLAN")

    plan = normalize_plan(
        create_consensus_plan(user_task, understandings, comparison))

    display_plan(plan)

    project_root = create_project_workspace(plan["project_name"])

    print_separator("PROJECT WORKSPACE CREATED")
    print(f"Location: {project_root}")

    try:
        return build_and_release(user_task, plan, project_root)

    except TaskStopped as error:
        error.project_root = project_root
        raise

    except Exception as error:
        raise TaskStopped(redact(error), project_root) from error


# ============================================================
# TASK MODE UI
# ============================================================

def run_task_mode():
    print_separator("AI TEAM - TASK MODE")

    print("Describe what you want AI TEAM to build, modify, create, "
          "or implement.")

    print("\nExamples:")
    print("  - Create a modern student expense tracker website")
    print("  - Build a Python CLI password manager")
    print("  - Create a C program for a library management system")
    print("  - Build a portfolio website")
    print("\nType 'back' to return to the main menu.\n")

    user_task = input("What should AI TEAM build? ").strip()

    if not user_task or user_task.lower() == "back":
        return

    try:
        execute_task(user_task)

    except KeyboardInterrupt:
        print("\n\nTask cancelled by user.")

    except Exception as error:
        print_separator("TASK MODE STOPPED SAFELY")
        print(f"Reason: {redact(error)}")

        root = getattr(error, "project_root", None)

        if root:
            print("\nPartial, UNVERIFIED workspace (not released): "
                  f"{Path(root).resolve()}")

        print("\nNo unchecked final project was released.")


# ============================================================
# DIRECT RUN
# ============================================================

if __name__ == "__main__":
    run_task_mode()