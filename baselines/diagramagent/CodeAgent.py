# code_agent.py
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# Parity with the EvoDiagram generator (evo_diagram/agentic_system/main.py uses
# max_tokens=16384 / max_retries=6; configs/models.yaml pins temperature 0).
LLM_MAX_RETRIES = 6
LLM_MAX_TOKENS = 16384
LLM_TEMPERATURE = 0

class CodeAgent:
    def __init__(self, model_path="DiagramAgent/Code_Agent", device="cuda", env_path: Optional[str] = None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(env_path or os.path.join(base_dir, ".env"), override=True)

        self.llm_api_key, self.llm_base_url = self._pick_llm_endpoint()
        self.llm_model = (os.getenv("ELYSIVER_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
        # This agent does not inherit BaseAgent, so the retry/decoding settings
        # EvoDiagram gets for free have to be set here explicitly.
        self.client = OpenAI(
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            max_retries=LLM_MAX_RETRIES,
        )
        self.device = device

    def generate_code(self, query: str, original_code: str = None, task: str = "generation") -> str:
        """
        task: "generation" | "editing"
        """
        if task == "generation":
            prompt = self._build_generation_prompt(query)
        else:  # editing
            prompt = self._build_editing_prompt(query, original_code)

        resp = self.client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": "You are an expert in LaTeX TikZ and Graphviz DOT. Return ONLY the complete code."},
                {"role": "user", "content": prompt},
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        code = resp.choices[0].message.content or ""
        return self._extract_code_block(code)

    def _build_generation_prompt(self, query: str) -> str:
        # 基于论文 Figure 11 的 prompt
        return f"""You are an expert in TikZ and DOT diagram generation.
Generate complete, compilable code based on the following instruction.
Use LaTeX TikZ for architecture diagrams, flowcharts, mind maps, etc.
Use DOT for directed/undirected graphs.

Instruction: {query}

Generate the complete code:"""

    def _build_editing_prompt(self, query: str, original_code: str) -> str:
        # 基于论文 Figure 12 的 prompt
        return f"""You are an expert at modifying diagram code.
Return the fully modified code according to the user's instructions.

User Instruction: {query}

Original Code:
{original_code}

Output the complete modified code:"""

    def _extract_code_block(self, text: str) -> str:
        """提取代码块"""
        import re
        patterns = [
            r'```(?:latex|tikz|dot)?\n(.*?)```',
            r'\\documentclass.*?\\end{document}',
            r'digraph\s*\{.*?\}'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                # The fenced pattern captures the body in group(1); group(0)
                # would keep the ``` fences and break pdflatex on line 1.
                return match.group(1) if match.groups() else match.group(0)
        return text.strip()

    def _normalize_base_url(self, base_url: str) -> str:
        u = (base_url or "").strip().strip('"').strip("'")
        if not u:
            return ""
        if not (u.startswith("http://") or u.startswith("https://")):
            u = "https://" + u
        u = u.rstrip("/")
        if u.endswith("/chat/completions"):
            u = u[: -len("/chat/completions")]
        if u.endswith("/v1"):
            return u
        return u + "/v1"

    def _pick_llm_endpoint(self) -> tuple[str, str]:
        ely_key = (os.getenv("ELYSIVER_API_KEY") or "").strip()
        ely_base = self._normalize_base_url(os.getenv("ELYSIVER_BASE_URL") or "")
        if ely_key and ely_base:
            return ely_key, ely_base

        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        openai_base = self._normalize_base_url(os.getenv("OPENAI_BASE_URL") or "")
        if openai_key and openai_base:
            return openai_key, openai_base

        raise RuntimeError("Missing API config: ELYSIVER_API_KEY/ELYSIVER_BASE_URL or OPENAI_API_KEY/OPENAI_BASE_URL")
