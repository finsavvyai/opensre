"""GitHub Copilot CLI adapter (``copilot -p``, non-interactive / programmatic mode).

Env vars
--------
COPILOT_BIN     Optional explicit path to the ``copilot`` binary.
                Blank or non-runnable paths are ignored; PATH + fallbacks apply.
COPILOT_MODEL   Optional model override (e.g. ``gpt-5.2``, ``claude-sonnet-4.6``).
                Unset or empty → omit ``--model``; CLI default applies.
COPILOT_HOME    Optional config directory override. Defaults to ``~/.copilot``.

Auth
----
Copilot CLI has no scriptable ``auth status`` subcommand — login is the
interactive ``/login`` slash command, which writes credentials under
``$COPILOT_HOME`` (default ``~/.copilot``). Probe order:

1. Run ``copilot --version`` to confirm the binary works (``installed``).
2. Treat the presence of a non-empty ``$COPILOT_HOME`` directory as the
   primary positive auth signal (where ``/login`` stores credentials).
3. Fall back to ``COPILOT_GITHUB_TOKEN`` / ``GH_TOKEN`` / ``GITHUB_TOKEN``
   if no stored credentials are found — the CLI accepts these too.
4. If nothing matches, report ``logged_in=None`` (auth state unclear);
   the runner will surface the auth hint if invocation fails.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from app.integrations.llm_cli.base import CLIInvocation, CLIProbe
from app.integrations.llm_cli.binary_resolver import (
    candidate_binary_names as _candidate_binary_names,
)
from app.integrations.llm_cli.binary_resolver import (
    default_cli_fallback_paths as _default_cli_fallback_paths,
)
from app.integrations.llm_cli.binary_resolver import (
    resolve_cli_binary,
)
from app.integrations.llm_cli.env_overrides import (
    COPILOT_CLI_ENV_KEYS,
    nonempty_env_values,
)

_COPILOT_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")
_PROBE_TIMEOUT_SEC = 5.0
_AUTH_HINT = "Run `copilot` then /login, or set COPILOT_GITHUB_TOKEN / GH_TOKEN / GITHUB_TOKEN."


def _parse_semver(text: str) -> str | None:
    m = _COPILOT_VERSION_RE.search(text)
    return m.group(1) if m else None


def _copilot_home() -> Path:
    override = os.environ.get("COPILOT_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".copilot"


def _stored_credentials_present() -> bool:
    """True when ``$COPILOT_HOME`` exists and is non-empty.

    The interactive ``/login`` device flow writes credentials beneath this
    directory; treating it as "auth present" mirrors how ``claude_code``
    treats ``~/.claude/.credentials.json``. We do not parse the file format
    because Copilot CLI does not document a stable schema.
    """
    home = _copilot_home()
    try:
        if not home.is_dir():
            return False
        return any(home.iterdir())
    except OSError:
        return False


def _has_token_env() -> str | None:
    """Return the first set token env var name, if any."""
    for key in COPILOT_CLI_ENV_KEYS:
        if os.environ.get(key, "").strip():
            return key
    return None


def _classify_copilot_auth() -> tuple[bool | None, str]:
    """Resolve auth state without spawning the CLI (no scriptable auth probe)."""
    if _stored_credentials_present():
        return True, f"Authenticated via {_copilot_home()} (stored Copilot CLI credentials)."
    token_key = _has_token_env()
    if token_key:
        return True, f"Authenticated via {token_key}."
    return None, f"Could not verify Copilot CLI auth. {_AUTH_HINT}"


def _fallback_copilot_paths() -> list[str]:
    return _default_cli_fallback_paths("copilot")


class CopilotAdapter:
    """Non-interactive GitHub Copilot CLI (``copilot -p``, programmatic mode)."""

    name = "copilot"
    binary_env_key = "COPILOT_BIN"
    install_hint = "npm i -g @github/copilot"
    auth_hint = _AUTH_HINT.removesuffix(".")
    min_version: str | None = None
    default_exec_timeout_sec = 180.0

    def _resolve_binary(self) -> str | None:
        return resolve_cli_binary(
            explicit_env_key="COPILOT_BIN",
            binary_names=_candidate_binary_names("copilot"),
            fallback_paths=_fallback_copilot_paths,
        )

    def _probe_binary(self, binary_path: str) -> CLIProbe:
        try:
            ver_proc = subprocess.run(
                [binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_SEC,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CLIProbe(
                installed=False,
                version=None,
                logged_in=None,
                bin_path=None,
                detail=f"Could not run `{binary_path} --version`: {exc}",
            )

        if ver_proc.returncode != 0:
            err = (ver_proc.stderr or ver_proc.stdout or "").strip()
            return CLIProbe(
                installed=False,
                version=None,
                logged_in=None,
                bin_path=None,
                detail=f"`{binary_path} --version` failed: {err or 'unknown error'}",
            )

        version = _parse_semver(ver_proc.stdout + ver_proc.stderr)
        logged_in, auth_detail = _classify_copilot_auth()
        return CLIProbe(
            installed=True,
            version=version,
            logged_in=logged_in,
            bin_path=binary_path,
            detail=auth_detail,
        )

    def detect(self) -> CLIProbe:
        binary = self._resolve_binary()
        if not binary:
            return CLIProbe(
                installed=False,
                version=None,
                logged_in=None,
                bin_path=None,
                detail=(
                    "Copilot CLI not found on PATH or known install locations. "
                    f"Install with: {self.install_hint} or set COPILOT_BIN."
                ),
            )
        return self._probe_binary(binary)

    def build(self, *, prompt: str, model: str | None, workspace: str) -> CLIInvocation:
        binary = self._resolve_binary()
        if not binary:
            raise RuntimeError(
                f"Copilot CLI not found. {self.install_hint} "
                "or set COPILOT_BIN to the full binary path."
            )

        ws = (workspace or "").strip()
        cwd = str(Path(ws).expanduser()) if ws else os.getcwd()

        argv: list[str] = [
            binary,
            "-p",
            prompt,
            "--no-color",
            "--no-banner",
            "--no-ask-user",
            "--silent",
            "--log-level",
            "none",
        ]

        resolved_model = (model or "").strip()
        if resolved_model:
            argv.extend(["--model", resolved_model])

        env = nonempty_env_values(COPILOT_CLI_ENV_KEYS)
        return CLIInvocation(
            argv=tuple(argv),
            stdin=None,
            cwd=cwd,
            env=env or None,
            timeout_sec=self.default_exec_timeout_sec,
        )

    def parse(self, *, stdout: str, stderr: str, returncode: int) -> str:
        del stderr, returncode
        return (stdout or "").strip()

    def explain_failure(self, *, stdout: str, stderr: str, returncode: int) -> str:
        err = (stderr or "").strip()
        out = (stdout or "").strip()
        bits = [f"copilot -p exited with code {returncode}"]
        text = f"{err}\n{out}".lower()
        # Match only specific auth phrases so we never mask a real error that
        # happens to contain the substring "login" (e.g. "Your current login:
        # alice — Error: model 'X' not found in your plan").
        auth_markers = (
            "not logged in",
            "not authenticated",
            "no credentials",
            "please /login",
            "unauthorized",
            "401",
        )
        is_auth_error = any(marker in text for marker in auth_markers)
        if err:
            bits.append(err[:2000])
        elif out:
            bits.append(out[:2000])
        if is_auth_error:
            bits.append(_AUTH_HINT)
        return ". ".join(bits)
