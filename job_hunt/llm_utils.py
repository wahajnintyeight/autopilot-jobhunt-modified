import json
import os
import subprocess
import time
from typing import Any, cast

from openai import OpenAI, RateLimitError

from job_hunt.log import get_logger

logger = get_logger()

# Per-request timeout (seconds) for HTTP-based LLM providers. Without this the
# openai/anthropic SDKs default to 600s, so a single stalled free-tier model can
# freeze a scan for 10 minutes. claude_cli has its own subprocess timeout (300s).
_LLM_REQUEST_TIMEOUT = 120.0


def _make_openai_client(api_key: str | None, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, timeout=_LLM_REQUEST_TIMEOUT)


def _make_openrouter_client(config: dict) -> OpenAI:
    return OpenAI(
        api_key=config.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        timeout=_LLM_REQUEST_TIMEOUT,
    )


def _chat_openai_compatible(
    llm: OpenAI,
    config: dict,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    *,
    primary_key: str,
    fallback_key: str,
    default_primary: str,
    default_fallbacks: tuple[str, ...] = (),
) -> str:
    return chat_with_fallback(
        llm,
        config,
        messages,
        temperature,
        max_tokens,
        primary_key=primary_key,
        fallback_key=fallback_key,
        default_primary=default_primary,
        default_fallbacks=default_fallbacks,
    )


def _chat_with_anthropic(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install 'autopilot-jobs[claude]'")
    api_key = config.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY")
    model = config.get("anthropic_model", "claude-haiku-4-5-20251001")
    logger.debug(f"LLM call → Anthropic / {model}")
    t0 = time.time()
    client = anthropic.Anthropic(api_key=api_key, timeout=_LLM_REQUEST_TIMEOUT)
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    kwargs: dict = {
        "model": model,
        "messages": user_msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system
    r = client.messages.create(**kwargs)
    elapsed = time.time() - t0
    text = r.content[0].text
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s (input={r.usage.input_tokens} out={r.usage.output_tokens} tokens)")
    return text


def _chat_with_claude_cli(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    model = config.get("claude_cli_model", "")
    logger.debug(f"LLM call → Claude CLI{' / ' + model if model else ''}")
    t0 = time.time()

    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    prompt_text = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in user_msgs)

    # --strict-mcp-config suppresses all MCP servers in the subprocess; reduces ~27k context tokens
    cmd = [
        "claude", "--print", "--output-format", "json", "--tools", "",
        "--mcp-config", '{"mcpServers":{}}', "--strict-mcp-config",
        "--disable-slash-commands",
    ]
    if system:
        cmd += ["--system-prompt", system]
    if model:
        cmd += ["--model", model]

    try:
        result = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude binary not found in PATH.\n"
            "Install Claude Code from https://claude.ai/code and run 'claude auth login'."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("claude CLI timed out after 300s.")

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            text = data.get("result")
            if text is None:
                raise KeyError("no 'result' field in output")
        elif isinstance(data, list):
            result_event = next((e for e in data if isinstance(e, dict) and e.get("type") == "result"), None)
            if result_event is None:
                raise KeyError("no 'result' event found in output")
            text = result_event["result"]
        else:
            raise TypeError(f"unexpected output type: {type(data)}")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(f"claude CLI unexpected output ({e}): {result.stdout[:200]}")

    elapsed = time.time() - t0
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via claude CLI")
    return text


def _chat_with_deepseek(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    api_key = config.get("deepseek_api_key") or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set. Add it to your .env file.")
    model = config.get("deepseek_model", "deepseek-v4-flash")
    logger.debug(f"LLM call → DeepSeek / {model}")
    llm = _make_openai_client(api_key, "https://api.deepseek.com")
    return _chat_openai_compatible(
        llm,
        config,
        messages,
        temperature,
        max_tokens,
        primary_key="deepseek_model",
        fallback_key="deepseek_fallback_models",
        default_primary=model,
        default_fallbacks=("deepseek-v4-pro",),
    )


def _chat_with_huggingface(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    api_key = (
        config.get("huggingface_api_key")
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    )
    model = config.get("huggingface_model") or os.getenv("HUGGINGFACE_MODEL")
    if not api_key:
        raise RuntimeError("HF_TOKEN not set. Add it to your .env file.")
    if not model:
        raise RuntimeError("huggingface_model not set. Add it to config.json or .env.")
    logger.debug(f"LLM call → Hugging Face / {model}")
    llm = _make_openai_client(api_key, "https://router.huggingface.co/v1")
    return _chat_openai_compatible(
        llm,
        config,
        messages,
        temperature,
        max_tokens,
        primary_key="huggingface_model",
        fallback_key="huggingface_fallback_models",
        default_primary=model,
    )


def chat_with_llm(
    config: dict,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> str:
    provider = (config.get("llm_provider") or "openrouter").lower()
    if provider == "anthropic":
        return _chat_with_anthropic(config, messages, temperature, max_tokens)
    if provider == "claude_cli":
        return _chat_with_claude_cli(config, messages, temperature, max_tokens)
    if provider == "deepseek":
        return _chat_with_deepseek(config, messages, temperature, max_tokens)
    if provider in ("huggingface", "hf"):
        return _chat_with_huggingface(config, messages, temperature, max_tokens)
    return chat_with_fallback(_make_openrouter_client(config), config, messages, temperature, max_tokens)


def chat_with_fallback(
    llm: OpenAI,
    config: dict,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
    *,
    primary_key: str = "openrouter_model",
    fallback_key: str = "openrouter_fallback_models",
    default_primary: str = "nvidia/nemotron-3-super-120b-a12b:free",
    default_fallbacks: tuple[str, ...] = (),
    provider_hint: str = "openrouter",
) -> str:
    primary = config.get(primary_key, default_primary)
    fallbacks = config.get(fallback_key, list(default_fallbacks))
    models = [primary] + [m for m in fallbacks if m != primary]

    # Map provider -> the env var / config key that holds its API key, so the
    # final error message points at the right credential instead of always
    # blaming OpenRouter.
    provider = (config.get("llm_provider") or provider_hint).lower()
    credential_hint = {
        "openrouter": "OPENROUTER_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "huggingface": "HUGGINGFACE_API_KEY",
        "hf": "HUGGINGFACE_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(provider, "OPENROUTER_API_KEY")

    failures: list[str] = []
    for model_idx, model in enumerate(models):
        label = f"[model {model_idx + 1}/{len(models)}] {model}"
        for attempt in range(2):
            try:
                logger.debug(f"LLM call → {label} (attempt {attempt + 1})")
                t0 = time.time()
                resp = llm.chat.completions.create(
                    model=model,
                    messages=cast("Any", messages),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                elapsed = time.time() - t0
                text = resp.choices[0].message.content or ""
                usage = resp.usage
                if usage:
                    logger.debug(
                        f"LLM response: {len(text)} chars in {elapsed:.1f}s "
                        f"(in={usage.prompt_tokens} out={usage.completion_tokens} tokens) via {model}"
                    )
                else:
                    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via {model}")
                return text
            except RateLimitError:
                if attempt == 0:
                    logger.warning(f"Rate-limited on {model} — retrying in 3s...")
                    time.sleep(3)
                    continue
                logger.warning(f"Rate-limited on {model} (quota exhausted) — trying next model...")
                failures.append(f"{model}: rate limit / quota exhausted")
                break
            except Exception as e:
                logger.error(f"LLM error ({model}): {e}")
                failures.append(f"{model}: {e}")
                break

    detail = "; ".join(failures) if failures else "unknown error"
    raise RuntimeError(
        f"All {provider} models failed ({len(failures)}/{len(models)} tried). "
        f"Check {credential_hint} and quota. Failures: {detail}"
    )
