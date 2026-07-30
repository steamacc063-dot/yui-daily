"""LLM client layer for Perplexity APIs and Codex CLI execution.

Architecture
────────────
• **PerplexityClient** talks to the Perplexity Agent, Sonar, and Search APIs.
• **CodexCLIClient** shells out to the local Codex CLI for fully local agent routing.
• **BackupLLMClient** adds provider-level fallback (for example: Perplexity → Codex).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger("yui.llm")

API_BASE = "https://api.perplexity.ai"
DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_CODEX_TIMEOUT_SECONDS = 60

CODEX_MINIMAL_OVERRIDES: tuple[str, ...] = (
    'notify=[]',
    'developer_instructions=""',
    'features.child_agents_md=false',
    'features.multi_agent=false',
    'mcp_servers.playwright.enabled=false',
    'mcp_servers.figma.enabled=false',
    'mcp_servers.omx_state.enabled=false',
    'mcp_servers.omx_trace.enabled=false',
    'mcp_servers.omx_memory.enabled=false',
    'mcp_servers.omx_team_run.enabled=false',
    'mcp_servers.omx_code_intel.enabled=false',
)

CODEX_NETWORK_FAILURE_PATTERNS: tuple[str, ...] = (
    "failed to lookup address information",
    "error sending request for url (https://chatgpt.com/backend-api/codex/responses)",
    "failed to connect to websocket",
)

CODEX_AUTH_FAILURE_PATTERNS: tuple[str, ...] = (
    "run `codex login`",
    "not authenticated",
    "authentication required",
)

# ── Available models ─────────────────────────────────────────────────────────

AGENT_MODELS: dict[str, str] = {
    # Perplexity
    "sonar": "perplexity/sonar",
    # OpenAI
    "gpt-5.4": "openai/gpt-5.4",
    "gpt-5.2": "openai/gpt-5.2",
    "gpt-5.1": "openai/gpt-5.1",
    "gpt-5-mini": "openai/gpt-5-mini",
    # Anthropic
    "claude-opus-4-6": "anthropic/claude-opus-4-6",
    "claude-opus-4-5": "anthropic/claude-opus-4-5",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4-6",
    "claude-sonnet-4-5": "anthropic/claude-sonnet-4-5",
    "claude-haiku-4-5": "anthropic/claude-haiku-4-5",
    # Google
    "gemini-3.1-pro": "google/gemini-3.1-pro-preview",
    "gemini-3-flash": "google/gemini-3-flash-preview",
    # xAI
    "grok-4-fast": "xai/grok-4-1-fast-non-reasoning",
    # NVIDIA
    "nemotron-3": "nvidia/nemotron-3-super-120b-a12b",
}

SONAR_MODELS: list[str] = ["sonar", "sonar-pro", "sonar-reasoning-pro"]

DEFAULT_AGENT_MODEL = "perplexity/sonar"
DEFAULT_RESEARCH_MODEL = "sonar-reasoning-pro"

# Reasoning effort mapping
REASONING_EFFORTS: dict[str, dict[str, Any] | None] = {
    "off": None,
    "low": {"effort": "low"},
    "medium": {"effort": "medium"},
    "high": {"effort": "high"},
}


class BaseLLMClient:
    """Shared interface for all model backends."""

    provider_name = "base"

    def __init__(
        self,
        *,
        model: str,
        research_model: str,
        temperature: float = 0.4,
        max_output_tokens: int = 16384,
        reasoning: str = "high",
        web_search: bool = True,
        fetch_url: bool = True,
        search_recency_filter: str = "none",
    ) -> None:
        self.model = model
        self.research_model = research_model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.reasoning = reasoning
        self.web_search = web_search
        self.fetch_url = fetch_url
        self.search_recency_filter = search_recency_filter

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        """Send a non-streaming chat request."""
        raise NotImplementedError

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat response. Backends may fall back to a single chunk."""
        response = await self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )
        if response:
            yield response

    async def research(
        self,
        query: str,
        system: str = "Be precise and comprehensive. Cite sources.",
        model: str | None = None,
    ) -> str:
        """Run a research-oriented query."""
        raise NotImplementedError

    async def search(
        self,
        query: str,
        max_results: int = 10,
        country: str = "",
    ) -> list[dict[str, str]]:
        """Return structured search results when supported."""
        raise NotImplementedError

    async def ping(self) -> bool:
        """Return True when the backend is usable."""
        raise NotImplementedError

    async def summarize(
        self,
        text: str,
        instruction: str = "Summarize concisely.",
    ) -> str:
        """Summarize a text block through the active backend."""
        return await self.chat(
            [
                {"role": "system", "content": instruction},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            max_tokens=1024,
        )

    async def close(self) -> None:
        """Release any backend resources."""
        return None


def resolve_model(name: str) -> str:
    """Resolve a short model name to its full provider/model identifier."""
    if "/" in name:
        return name  # already fully qualified
    return AGENT_MODELS.get(name, name)



def list_models() -> dict[str, list[str]]:
    """Return all available models grouped by category."""
    return {
        "Agent API": sorted(AGENT_MODELS.values()),
        "Sonar (Research)": SONAR_MODELS,
    }


class PerplexityClient(BaseLLMClient):
    """Unified async client for all three Perplexity APIs."""

    provider_name = "perplexity"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_AGENT_MODEL,
        research_model: str = DEFAULT_RESEARCH_MODEL,
        timeout: float = 180.0,
        temperature: float = 0.4,
        max_output_tokens: int = 16384,
        reasoning: str = "high",
        web_search: bool = True,
        fetch_url: bool = True,
        search_recency_filter: str = "none",
    ) -> None:
        super().__init__(
            model=resolve_model(model),
            research_model=research_model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning=reasoning,
            web_search=web_search,
            fetch_url=fetch_url,
            search_recency_filter=search_recency_filter,
        )
        self.api_key = api_key
        self._http = httpx.AsyncClient(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _fallback_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Build fallback payload variants for 400 recovery."""
        variants = [payload]
        if "reasoning" in payload:
            p = dict(payload)
            p.pop("reasoning", None)
            variants.append(p)
        if "tools" in payload:
            p = dict(payload)
            p.pop("tools", None)
            variants.append(p)
        if "reasoning" in payload and "tools" in payload:
            p = dict(payload)
            p.pop("reasoning", None)
            p.pop("tools", None)
            variants.append(p)
        return variants

    def _build_tools(self, extra_tools: list[dict] | None = None) -> list[dict] | None:
        """Build the tools list from config + any extras."""
        tools: list[dict[str, Any]] = []
        if self.web_search:
            tool_def: dict[str, Any] = {"type": "web_search"}
            if self.search_recency_filter and self.search_recency_filter != "none":
                tool_def["search_recency_filter"] = self.search_recency_filter
            tools.append(tool_def)
        if self.fetch_url:
            tools.append({"type": "fetch_url"})
        if extra_tools:
            tools.extend(extra_tools)
        return tools if tools else None

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build the Agent API request payload."""
        resolved = resolve_model(model) if model else self.model
        user_input = messages[-1]["content"] if messages else ""
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        instructions = "\n\n".join(system_parts) if system_parts else None

        input_items: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] in ("user", "assistant"):
                input_items.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        payload: dict[str, Any] = {
            "model": resolved,
            "input": input_items if len(input_items) > 1 else user_input,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_output_tokens": max_tokens if max_tokens is not None else self.max_output_tokens,
        }

        if stream:
            payload["stream"] = True

        if instructions:
            payload["instructions"] = instructions

        reasoning_cfg = REASONING_EFFORTS.get(self.reasoning)
        if reasoning_cfg:
            payload["reasoning"] = reasoning_cfg

        merged_tools = self._build_tools(tools)
        if merged_tools:
            payload["tools"] = merged_tools

        return payload

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        """Send a request through the Agent API and return the text response."""
        payload = self._build_payload(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, tools=tools,
        )

        last_exc: httpx.HTTPStatusError | None = None
        for i, candidate in enumerate(self._fallback_payloads(payload), start=1):
            try:
                resp = await self._http.post("/v1/agent", json=candidate)
                resp.raise_for_status()
                data = resp.json()
                if i > 1:
                    log.warning("Agent API succeeded with fallback payload #%d", i)
                return self._extract_agent_text(data)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                text = exc.response.text
                log.error("Agent API error %s: %s", status, text)
                if status != 400:
                    raise
                if i == len(self._fallback_payloads(payload)):
                    raise
                continue
            except Exception as exc:
                log.error("Agent API request failed: %s", exc)
                raise

        if last_exc:
            raise last_exc
        raise RuntimeError("Agent API request failed unexpectedly")

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens from the Agent API via SSE."""
        payload = self._build_payload(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, tools=tools, stream=True,
        )

        async with self._http.stream("POST", "/v1/agent", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                    event_type = obj.get("type", "")
                    if event_type == "response.output_text.delta":
                        delta = obj.get("delta", "")
                        if delta:
                            yield delta
                except (json.JSONDecodeError, KeyError):
                    continue

    async def research(
        self,
        query: str,
        system: str = "Be precise and comprehensive. Cite sources.",
        model: str | None = None,
    ) -> str:
        """Web-grounded research using the Sonar API."""
        payload = {
            "model": model or self.research_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }
        try:
            resp = await self._http.post("/v1/sonar", json=payload)
            resp.raise_for_status()
            data = resp.json()

            answer = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            if citations:
                cite_lines = [f"[{i+1}] {url}" for i, url in enumerate(citations)]
                answer += "\n\nSources:\n" + "\n".join(cite_lines)

            return answer
        except httpx.HTTPStatusError as exc:
            log.error(
                "Sonar API error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        except Exception as exc:
            log.error("Sonar API request failed: %s", exc)
            raise

    async def search(
        self,
        query: str,
        max_results: int = 10,
        country: str = "",
    ) -> list[dict[str, str]]:
        """Raw web search via the Search API. Returns structured results."""
        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
        }
        if country:
            payload["country"] = country

        try:
            resp = await self._http.post("/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
        except httpx.HTTPStatusError as exc:
            log.error(
                "Search API error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        except Exception as exc:
            log.error("Search API request failed: %s", exc)
            raise

    async def ping(self) -> bool:
        """Quick connection test — True if the Agent API responds."""
        try:
            resp = await self._http.post(
                "/v1/agent",
                json={
                    "model": self.model,
                    "input": "hi",
                    "max_output_tokens": 5,
                },
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    @staticmethod
    def _extract_agent_text(data: dict) -> str:
        """Extract the text content from an Agent API response."""
        parts: list[str] = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        parts.append(content["text"])
        return "\n".join(parts) if parts else ""


class CodexCLIClient(BaseLLMClient):
    """Local backend that runs prompts through the installed Codex CLI."""

    provider_name = "codex"

    def __init__(
        self,
        command: str = "codex",
        model: str = DEFAULT_CODEX_MODEL,
        timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
        workspace_root: str | Path | None = None,
        vault_path: str | Path | None = None,
        temperature: float = 0.4,
        max_output_tokens: int = 16384,
        reasoning: str = "high",
        web_search: bool = True,
        fetch_url: bool = True,
        search_recency_filter: str = "none",
    ) -> None:
        effective_model = model or DEFAULT_CODEX_MODEL
        super().__init__(
            model=effective_model,
            research_model=effective_model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning=reasoning,
            web_search=web_search,
            fetch_url=fetch_url,
            search_recency_filter=search_recency_filter,
        )
        self.command = command
        self.timeout_seconds = max(30, int(timeout_seconds))
        self.workspace_root = Path(workspace_root or Path.cwd()).expanduser().resolve()
        self.vault_path = (
            Path(vault_path).expanduser().resolve() if vault_path else None
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        """Run a multi-message chat turn through Codex CLI."""
        del temperature, max_tokens, tools
        prompt = self._format_messages(messages)
        prompt += self._search_guidance(enabled=self.web_search or self.fetch_url)
        return await self._run_codex(
            prompt,
            model=model or self.model,
            enable_search=self.web_search or self.fetch_url,
        )

    async def research(
        self,
        query: str,
        system: str = "Be precise and comprehensive. Cite sources.",
        model: str | None = None,
    ) -> str:
        """Run a research query via Codex CLI with live web search enabled."""
        prompt = (
            f"{system.strip()}\n\n"
            "Use live web search aggressively. Prefer current, primary sources. "
            "Include a final Sources section with URLs.\n\n"
            f"Research query: {query.strip()}"
        )
        prompt += self._search_guidance(enabled=True)
        return await self._run_codex(
            prompt,
            model=model or self.model,
            enable_search=True,
        )

    async def search(
        self,
        query: str,
        max_results: int = 10,
        country: str = "",
    ) -> list[dict[str, str]]:
        """Use Codex CLI web search and coerce the result into structured JSON."""
        country_note = f" Country hint: {country}." if country else ""
        prompt = (
            "Search the web and return ONLY valid JSON as an array. "
            f"Include at most {max_results} results. Each result must have keys "
            '"title", "url", and "snippet".'
            f"{country_note}\n\n"
            f"Query: {query.strip()}"
        )
        raw = await self._run_codex(prompt, model=self.model, enable_search=True)
        return self._parse_search_results(raw)

    async def ping(self) -> bool:
        """Check whether Codex CLI can complete a trivial non-interactive run."""
        if self._resolve_command() is None:
            return False

        original_timeout = self.timeout_seconds
        self.timeout_seconds = min(self.timeout_seconds, 20)
        try:
            response = await self._run_codex(
                "Reply with exactly: READY",
                model=self.model,
                enable_search=False,
            )
            return response.strip().upper() == "READY"
        except Exception:
            return False
        finally:
            self.timeout_seconds = original_timeout

    async def close(self) -> None:
        """Codex CLI has no persistent network resources to release."""
        return None

    def _resolve_command(self) -> str | None:
        """Return an executable path for the configured Codex command."""
        cmd_path = shutil.which(self.command)
        if cmd_path:
            return cmd_path
        direct = Path(self.command).expanduser()
        if direct.exists() and os.access(direct, os.X_OK):
            return str(direct.resolve())
        return None

    def _build_command(
        self,
        *,
        output_file: Path,
        model: str,
        enable_search: bool,
    ) -> list[str]:
        """Construct the Codex CLI subprocess invocation."""
        resolved = self._resolve_command()
        if not resolved:
            raise RuntimeError(
                "Codex CLI executable not found: "
                f"{self.command}. Install Codex CLI or update codex_command."
            )

        cmd = [
            resolved,
        ]
        if enable_search:
            cmd.append("--search")
        for override in CODEX_MINIMAL_OVERRIDES:
            cmd.extend(["-c", override])
        cmd.extend([
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "workspace-write",
            "--color",
            "never",
            "-C",
            str(self.workspace_root),
            "-o",
            str(output_file),
        ])
        if self.vault_path and self.vault_path != self.workspace_root:
            cmd.extend(["--add-dir", str(self.vault_path)])
        if model:
            cmd.extend(["--model", model])
        cmd.append("-")
        return cmd

    async def _run_codex(
        self,
        prompt: str,
        *,
        model: str,
        enable_search: bool,
    ) -> str:
        """Execute Codex CLI with a prompt and return the final message."""
        with tempfile.NamedTemporaryFile(prefix="yui-codex-", suffix=".txt", delete=False) as tmp:
            output_file = Path(tmp.name)

        cmd = self._build_command(
            output_file=output_file,
            model=model,
            enable_search=enable_search,
        )
        env = os.environ.copy()
        env.setdefault("OTEL_SDK_DISABLED", "true")
        env.setdefault("NO_COLOR", "1")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace_root),
            env=env,
        )

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        stdout_task = asyncio.create_task(self._read_stream(proc.stdout, stdout_chunks))
        stderr_task = asyncio.create_task(self._read_stream(proc.stderr, stderr_chunks))
        timed_out = False

        try:
            if proc.stdin:
                proc.stdin.write(prompt.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            while proc.returncode is None:
                stderr_text = self._decode_chunks(stderr_chunks)
                failure = self._classify_codex_failure(stderr_text)
                if failure:
                    proc.kill()
                    await proc.wait()
                    raise RuntimeError(failure)

                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    await asyncio.wait_for(proc.wait(), timeout=min(0.5, remaining))
                except asyncio.TimeoutError:
                    continue
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            await proc.wait()
        finally:
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        stdout_text = self._decode_chunks(stdout_chunks)
        stderr_text = self._decode_chunks(stderr_chunks)
        answer = ""
        try:
            answer = output_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            answer = ""
        finally:
            try:
                output_file.unlink(missing_ok=True)
            except Exception:
                pass

        failure = self._classify_codex_failure(stderr_text)
        if failure:
            raise RuntimeError(failure)

        if timed_out:
            raise RuntimeError(
                self._format_codex_timeout(
                    self.timeout_seconds,
                    stderr_text,
                    stdout_text,
                )
            )

        if proc.returncode != 0:
            raise RuntimeError(self._format_codex_error(proc.returncode, stdout_text, stderr_text))

        if answer:
            return answer

        raise RuntimeError(
            "Codex CLI completed without a final message."
            + (f"\n{stderr_text[:800]}" if stderr_text else "")
        )

    def _format_messages(self, messages: list[dict[str, str]]) -> str:
        """Serialize a chat transcript into a Codex-friendly prompt."""
        parts = [
            "You are responding inside the yui multi-agent terminal application.",
            "Follow system instructions exactly and preserve the conversation roles below.",
            "",
        ]
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "").strip()
            if not content:
                continue
            parts.append(f"[{role}]\n{content}\n")
        return "\n".join(parts).strip()

    def _search_guidance(self, *, enabled: bool) -> str:
        """Add a plain-language search hint for Codex-backed prompts."""
        if not enabled:
            return ""
        recency = self.search_recency_filter
        guidance = "\n\nLive web search is available. Use it when current information matters."
        if recency and recency != "none":
            guidance += f" Prefer sources from the last {recency}."
        return guidance

    @staticmethod
    async def _read_stream(stream, sink: list[bytes]) -> None:
        """Continuously read subprocess output into a byte buffer."""
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            sink.append(chunk)

    @staticmethod
    def _decode_chunks(chunks: list[bytes]) -> str:
        """Decode a subprocess byte buffer into text."""
        return b"".join(chunks).decode("utf-8", errors="replace").strip()

    @staticmethod
    def _classify_codex_failure(stderr_text: str) -> str | None:
        """Return a higher-signal user-facing Codex error when possible."""
        text = stderr_text.lower()
        if any(pattern in text for pattern in CODEX_NETWORK_FAILURE_PATTERNS):
            return (
                "Codex CLI could not reach OpenAI endpoints. "
                "Check network/DNS connectivity and Codex access on this machine.\n"
                f"{stderr_text[:1200]}".strip()
            )
        if any(pattern in text for pattern in CODEX_AUTH_FAILURE_PATTERNS):
            return (
                "Codex CLI is not authenticated. Run `codex login` in a terminal, "
                "then retry.\n"
                f"{stderr_text[:1200]}".strip()
            )
        return None

    @staticmethod
    def _format_codex_timeout(
        timeout_seconds: int,
        stderr_text: str,
        stdout_text: str,
    ) -> str:
        """Build a timeout error that preserves any partial subprocess diagnostics."""
        detail = stderr_text or stdout_text
        if detail:
            detail = detail[:1200] + ("\n…" if len(detail) > 1200 else "")
            return (
                f"Codex CLI timed out after {timeout_seconds}s.\n"
                f"{detail}"
            )
        return f"Codex CLI timed out after {timeout_seconds}s."

    @staticmethod
    def _parse_search_results(raw: str) -> list[dict[str, str]]:
        """Parse a JSON array of search results from Codex output."""
        text = raw.strip()
        if not text:
            return []
        if not text.startswith("["):
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        results: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            results.append({
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": str(item.get("snippet", "")),
            })
        return results

    @staticmethod
    def _format_codex_error(returncode: int, stdout_text: str, stderr_text: str) -> str:
        """Build a concise, human-readable error for failed Codex runs."""
        detail = stderr_text or stdout_text or "No diagnostic output from Codex CLI."
        detail = detail.strip()
        if len(detail) > 1200:
            detail = detail[:1200] + "\n…"
        return f"Codex CLI failed with exit code {returncode}.\n{detail}"


class BackupLLMClient(BaseLLMClient):
    """Provider wrapper that retries through a backup backend on failure."""

    provider_name = "backup"

    def __init__(self, primary: BaseLLMClient, backup: BaseLLMClient) -> None:
        self.primary = primary
        self.backup = backup

    @property
    def model(self) -> str:
        return self.primary.model

    @model.setter
    def model(self, value: str) -> None:
        self.primary.model = value

    @property
    def research_model(self) -> str:
        return self.primary.research_model

    @research_model.setter
    def research_model(self, value: str) -> None:
        self.primary.research_model = value

    @property
    def temperature(self) -> float:
        return self.primary.temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self.primary.temperature = value

    @property
    def max_output_tokens(self) -> int:
        return self.primary.max_output_tokens

    @max_output_tokens.setter
    def max_output_tokens(self, value: int) -> None:
        self.primary.max_output_tokens = value

    @property
    def reasoning(self) -> str:
        return self.primary.reasoning

    @reasoning.setter
    def reasoning(self, value: str) -> None:
        self.primary.reasoning = value

    @property
    def web_search(self) -> bool:
        return self.primary.web_search

    @web_search.setter
    def web_search(self, value: bool) -> None:
        self.primary.web_search = value

    @property
    def fetch_url(self) -> bool:
        return self.primary.fetch_url

    @fetch_url.setter
    def fetch_url(self, value: bool) -> None:
        self.primary.fetch_url = value

    @property
    def search_recency_filter(self) -> str:
        return self.primary.search_recency_filter

    @search_recency_filter.setter
    def search_recency_filter(self, value: str) -> None:
        self.primary.search_recency_filter = value

    async def chat(self, *args, **kwargs) -> str:
        return await self._with_backup("chat", *args, **kwargs)

    async def chat_stream(self, *args, **kwargs) -> AsyncIterator[str]:
        try:
            async for token in self.primary.chat_stream(*args, **kwargs):
                yield token
            return
        except Exception as exc:
            log.warning(
                "Primary backend %s failed during stream; falling back to %s: %s",
                self.primary.provider_name,
                self.backup.provider_name,
                exc,
            )
        async for token in self.backup.chat_stream(*args, **kwargs):
            yield token

    async def research(self, *args, **kwargs) -> str:
        return await self._with_backup("research", *args, **kwargs)

    async def search(self, *args, **kwargs) -> list[dict[str, str]]:
        return await self._with_backup("search", *args, **kwargs)

    async def ping(self) -> bool:
        if await self.primary.ping():
            return True
        return await self.backup.ping()

    async def summarize(self, *args, **kwargs) -> str:
        return await self._with_backup("summarize", *args, **kwargs)

    async def close(self) -> None:
        await self.primary.close()
        await self.backup.close()

    async def _with_backup(self, method: str, *args, **kwargs):
        try:
            return await getattr(self.primary, method)(*args, **kwargs)
        except Exception as exc:
            log.warning(
                "Primary backend %s failed; falling back to %s: %s",
                self.primary.provider_name,
                self.backup.provider_name,
                exc,
            )
            return await getattr(self.backup, method)(*args, **kwargs)


def create_llm_client(
    *,
    provider: str,
    backup_provider: str = "none",
    perplexity_api_key: str = "",
    model: str = DEFAULT_AGENT_MODEL,
    research_model: str = DEFAULT_RESEARCH_MODEL,
    codex_command: str = "codex",
    codex_model: str = DEFAULT_CODEX_MODEL,
    codex_timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
    temperature: float = 0.4,
    max_output_tokens: int = 16384,
    reasoning: str = "high",
    web_search: bool = True,
    fetch_url: bool = True,
    search_recency_filter: str = "none",
    workspace_root: str | Path | None = None,
    vault_path: str | Path | None = None,
) -> BaseLLMClient:
    """Create the configured LLM backend, optionally with a backup provider."""

    def _build(which: str) -> BaseLLMClient:
        if which == "perplexity":
            if not perplexity_api_key:
                raise RuntimeError("Perplexity provider selected but no API key is configured.")
            return PerplexityClient(
                api_key=perplexity_api_key,
                model=model,
                research_model=research_model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                reasoning=reasoning,
                web_search=web_search,
                fetch_url=fetch_url,
                search_recency_filter=search_recency_filter,
            )
        if which == "codex":
            return CodexCLIClient(
                command=codex_command,
                model=codex_model,
                timeout_seconds=codex_timeout_seconds,
                workspace_root=workspace_root,
                vault_path=vault_path,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                reasoning=reasoning,
                web_search=web_search,
                fetch_url=fetch_url,
                search_recency_filter=search_recency_filter,
            )
        raise RuntimeError(f"Unknown LLM provider: {which}")

    primary = _build(provider)
    if backup_provider and backup_provider != "none" and backup_provider != provider:
        return BackupLLMClient(primary, _build(backup_provider))
    return primary
