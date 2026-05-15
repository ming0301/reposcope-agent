"""统一 LLM 客户端工厂。

不写死模型或 API Key，通过环境变量配置。

环境变量:
  REPOSCOPE_MODEL         → 模型名（默认: deepseek-chat）
  REPOSCOPE_BASE_URL      → API 地址（默认: https://api.deepseek.com/v1）
  REPOSCOPE_API_KEY       → 直接设置 API Key（优先级最高）
  REPOSCOPE_API_KEY_ENV   → 指定从哪个环境变量读取 Key（默认: DEEPSEEK_API_KEY）
  REPOSCOPE_LLM_PROVIDER  → 厂商类型: "anthropic" 或 "openai"（默认: openai）

用法:
  # 默认 DeepSeek
  $env:DEEPSEEK_API_KEY="sk-..."

  # CC-Switch
  $env:REPOSCOPE_BASE_URL="http://localhost:8080/v1"
  $env:REPOSCOPE_MODEL="deepseek-chat"
  $env:REPOSCOPE_API_KEY="your-key-or-dummy"

  # Anthropic Claude
  $env:REPOSCOPE_LLM_PROVIDER="anthropic"
  $env:REPOSCOPE_MODEL="claude-sonnet-4-6"
  $env:REPOSCOPE_API_KEY_ENV="ANTHROPIC_API_KEY"
  $env:ANTHROPIC_API_KEY="sk-ant-..."

  # Qwen / 通义千问
  $env:REPOSCOPE_MODEL="qwen-plus"
  $env:REPOSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
  $env:DASHSCOPE_API_KEY="sk-..."
"""

from __future__ import annotations

import os

# ---- 默认值 ----

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_PROVIDER = "openai"


# ---- API Key ----

def get_api_key() -> str | None:
    """按优先级查找 API Key：
    1. REPOSCOPE_API_KEY（直接设置）
    2. REPOSCOPE_API_KEY_ENV 指定的变量 → 读取该变量
    3. DEFAULT_API_KEY_ENV
    """
    direct = os.environ.get("REPOSCOPE_API_KEY")
    if direct:
        return direct

    key_env_name = os.environ.get("REPOSCOPE_API_KEY_ENV", DEFAULT_API_KEY_ENV)
    return os.environ.get(key_env_name)


def require_api_key() -> str:
    """获取 API Key，未找到时抛出清晰错误。"""
    key = get_api_key()
    if key:
        return key

    key_env_name = os.environ.get("REPOSCOPE_API_KEY_ENV", DEFAULT_API_KEY_ENV)
    raise ValueError(
        f"未找到 API Key。请设置环境变量 REPOSCOPE_API_KEY，"
        f"或设置 {key_env_name}。"
    )


# ---- LLM 客户端 ----

def get_llm(
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0,
):
    """创建统一的 LLM 客户端（LangChain 兼容）。

    通过 REPOSCOPE_LLM_PROVIDER 判断厂商类型：
      - "anthropic" → ChatAnthropic
      - 其他（默认）→ ChatOpenAI（兼容 DeepSeek / Qwen / CC-Switch / 小米等）

    Args:
        model: 模型名（默认从 REPOSCOPE_MODEL 读取）
        base_url: API 地址（默认从 REPOSCOPE_BASE_URL 读取）
        api_key: API Key（默认从 get_api_key() 获取）
        temperature: 温度参数
    """
    model = model or os.environ.get("REPOSCOPE_MODEL", DEFAULT_MODEL)
    base_url = base_url or os.environ.get("REPOSCOPE_BASE_URL", DEFAULT_BASE_URL)
    api_key = api_key or require_api_key()

    provider = os.environ.get("REPOSCOPE_LLM_PROVIDER", DEFAULT_PROVIDER)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=api_key,
            temperature=temperature,
        )

    # 默认 OpenAI-compatible
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
    )
