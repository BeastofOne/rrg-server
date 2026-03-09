"""LangChain-compatible LLM wrapper around the Claude CLI.

Uses `claude -p` to send prompts to a local Claude instance.
No API key needed — just a Claude subscription and the CLI installed.
Each call is stateless — the full prompt is sent every time.
"""

import subprocess
from typing import Any, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class ChatClaudeCLI(BaseChatModel):
    """Chat model that shells out to the Claude CLI.

    Requires `claude` to be installed and available on PATH.
    Uses `claude -p` (prompt mode) with no tools — pure reasoning.
    Each call is stateless — the full prompt is sent every time.

    Args:
        model_name: Model to use (default "haiku"). Accepts "haiku", "sonnet",
                    "opus", or a full model ID like "claude-haiku-4-5".
        timeout: Max seconds to wait for a response (default 120).
        allowed_tools: Tools Claude can use. Empty string = no tools (pure
                       chatbot mode). Set to None to use CLI defaults.
    """

    model_name: str = "haiku"
    timeout: int = 120
    allowed_tools: Optional[str] = ""  # Empty string = no tools (pure chatbot)

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    def _format_messages(self, messages: List[BaseMessage]) -> tuple:
        """Convert LangChain messages into a prompt string and optional system prompt.

        Returns:
            (prompt_str, system_prompt_or_None)
        """
        system_parts = []
        conversation_parts = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_parts.append(msg.content)
            elif isinstance(msg, HumanMessage):
                conversation_parts.append(msg.content)
            elif isinstance(msg, AIMessage):
                conversation_parts.append(f"[Assistant]\n{msg.content}")
            else:
                conversation_parts.append(msg.content)

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        prompt = "\n\n".join(conversation_parts)
        return prompt, system_prompt

    def _build_command(self, prompt: str, system_prompt: Optional[str] = None) -> List[str]:
        """Build the Claude CLI command with appropriate flags."""
        cmd = ["claude", "-p", prompt, "--model", self.model_name, "--no-chrome"]

        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        # Strip tools for pure chatbot mode
        if self.allowed_tools is not None:
            cmd.extend(["--allowedTools", self.allowed_tools])

        return cmd

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Call Claude CLI with the formatted prompt."""
        prompt, system_prompt = self._format_messages(messages)
        cmd = self._build_command(prompt, system_prompt)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"Claude CLI exited with code {result.returncode}"
                raise RuntimeError(error_msg)

            content = result.stdout.strip()

        except FileNotFoundError:
            raise RuntimeError(
                "Claude CLI not found. Install it and make sure 'claude' is on your PATH."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Claude CLI timed out after {self.timeout}s")

        message = AIMessage(content=content)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])
