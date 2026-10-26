# plan_agent.py
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

class PlanAgent:
    def __init__(self, device="cuda", env_path: Optional[str] = None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(env_path or os.path.join(base_dir, ".env"), override=True)

        self.llm_api_key, self.llm_base_url = self._pick_llm_endpoint()
        self.llm_model = (os.getenv("ELYSIVER_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
        self.client = OpenAI(api_key=self.llm_api_key, base_url=self.llm_base_url)
        self.device = device

    def expand_query(self, user_query: str, task_type: str = "generation") -> str:
        """
        若指令不完整，进行查询扩展
        task_type: "generation" | "editing" | "coding"
        """
        if task_type == "generation":
            prompt = self._build_expansion_prompt(user_query)
        else:
            # editing/coding 任务直接透传
            return user_query

        resp = self.client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": "Rewrite and expand the user's instruction into a self-contained, precise diagram generation instruction."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()

    def _build_expansion_prompt(self, query: str) -> str:
        # 基于论文 Figure 8 的 prompt 模板
        return f"""You are an expert in expanding diagram creation instructions.
Analyze the following user query and expand it into a detailed, self-contained instruction.
The expanded query should specify: diagram type, components, labels, colors, layout preferences, and connections.

User Query: {query}

Expanded Query:"""

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
