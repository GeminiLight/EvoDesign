# check_agent.py
import re
import subprocess
import tempfile
import os
import shutil
import uuid
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# Parity with the EvoDiagram generator (evo_diagram/agentic_system/main.py uses
# max_tokens=16384 / max_retries=6; configs/models.yaml pins temperature 0).
LLM_MAX_RETRIES = 6
LLM_MAX_TOKENS = 16384
LLM_TEMPERATURE = 0

class CheckAgent:
    def __init__(self, use_gpt4o: bool = True, env_path: Optional[str] = None):
        self.use_gpt4o = use_gpt4o
        base_dir = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(env_path or os.path.join(base_dir, ".env"), override=True)

        self.llm_api_key, self.llm_base_url = self._pick_llm_endpoint()
        self.llm_model = (
            os.getenv("ELYSIVER_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "gpt-4o-mini"
        ).strip()

        self.client: Optional[OpenAI] = None
        if use_gpt4o and self.llm_api_key and self.llm_base_url:
            # Not a BaseAgent subclass, so the retry layer is set explicitly.
            self.client = OpenAI(
                api_key=self.llm_api_key,
                base_url=self.llm_base_url,
                max_retries=LLM_MAX_RETRIES,
            )

    def check(self, code: str, question: str, code_type: str = "tikz") -> dict:
        """
        两阶段检查：编译调试 + GPT-4o 验证
        返回: {"success": bool, "code": str, "errors": list, "suggestions": str}
        """
        # 阶段 1: 编译检查
        compile_result = self._compile_code(code, code_type)

        if not compile_result["success"]:
            # 编译失败，尝试修复
            fixed_code = self._fix_with_gpt4o(code, question, compile_result["errors"])
            compile_result = self._compile_code(fixed_code, code_type)
            code = fixed_code

        # 阶段 2: GPT-4o 语义验证
        if self.use_gpt4o and compile_result["success"]:
            verification = self._verify_with_gpt4o(code, question)
            if not verification["is_complete"]:
                # 根据建议修复；只有重新编译通过才采用，否则保留原本能编译的代码
                revised = self._apply_suggestions(code, verification["suggestions"])
                if revised and revised != code:
                    revised_result = self._compile_code(revised, code_type)
                    if revised_result["success"]:
                        code = revised
                        compile_result = revised_result

        return {
            "success": compile_result["success"],
            "code": code,
            "errors": compile_result.get("errors", []),
            "image_path": compile_result.get("output_path")
        }

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

        return "", ""

    def _ensure_tikz_document(self, code: str) -> str:
        s = (code or "").strip()
        if not s:
            return s
        if "\\documentclass" in s:
            return s

        has_tikzpicture = "\\begin{tikzpicture}" in s
        body = s if has_tikzpicture else f"\\begin{{tikzpicture}}\n{s}\n\\end{{tikzpicture}}"
        return (
            "\\documentclass[tikz,border=2pt]{standalone}\n"
            "\\usepackage{tikz}\n"
            "\\usetikzlibrary{arrows.meta,positioning,shapes.geometric,calc}\n"
            "\\begin{document}\n"
            f"{body}\n"
            "\\end{document}\n"
        )

    def _compile_code(self, code: str, code_type: str) -> dict:
        """编译 TikZ/DOT 代码"""
        with tempfile.TemporaryDirectory() as tmpdir:
            if code_type == "tikz":
                tex_path = os.path.join(tmpdir, "diagram.tex")
                with open(tex_path, "w") as f:
                    f.write(self._ensure_tikz_document(code))

                # 编译 LaTeX
                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-output-directory", tmpdir, tex_path],
                    capture_output=True, text=True, timeout=60
                )

                pdf_path = os.path.join(tmpdir, "diagram.pdf")
                success = os.path.exists(pdf_path) and result.returncode == 0

                # 转换为 PNG 用于后续评估
                png_path = None
                if success:
                    png_path = os.path.join(tmpdir, "diagram.png")
                    subprocess.run([
                        "pdftoppm", "-png", "-r", "150",
                        pdf_path, os.path.join(tmpdir, "diagram")
                    ], check=True)
                    # pdftoppm 输出为 diagram-1.png
                    generated = os.path.join(tmpdir, "diagram-1.png")
                    if os.path.exists(generated):
                        persistent_dir = os.path.join(tempfile.gettempdir(), "diagramagent_compile_outputs")
                        os.makedirs(persistent_dir, exist_ok=True)
                        persistent_path = os.path.join(persistent_dir, f"{uuid.uuid4().hex}.png")
                        shutil.copy2(generated, persistent_path)
                        png_path = persistent_path

                return {
                    "success": success,
                    "errors": (
                        [self._latex_diagnostics(result.stdout, result.stderr)]
                        if not success
                        else []
                    ),
                    "output_path": png_path
                }

            elif code_type == "dot":
                dot_path = os.path.join(tmpdir, "diagram.dot")
                png_path = os.path.join(tmpdir, "diagram.png")
                with open(dot_path, "w") as f:
                    f.write(code)

                result = subprocess.run(
                    ["dot", "-Tpng", dot_path, "-o", png_path],
                    capture_output=True, text=True
                )

                persistent_png = None
                if result.returncode == 0 and os.path.exists(png_path):
                    persistent_dir = os.path.join(tempfile.gettempdir(), "diagramagent_compile_outputs")
                    os.makedirs(persistent_dir, exist_ok=True)
                    persistent_png = os.path.join(persistent_dir, f"{uuid.uuid4().hex}.png")
                    shutil.copy2(png_path, persistent_png)

                return {
                    "success": result.returncode == 0,
                    "errors": [result.stderr] if result.returncode != 0 else [],
                    "output_path": persistent_png if result.returncode == 0 else None
                }

    @staticmethod
    def _latex_diagnostics(stdout: str, stderr: str, max_chars: int = 4000) -> str:
        """Collect pdflatex diagnostics.

        With ``-interaction=nonstopmode`` pdflatex reports errors on stdout and
        leaves stderr empty, so reading stderr alone produced an empty error
        section in the self-repair prompt.
        """
        lines = (stdout or "").splitlines()
        picked: list[str] = []
        for i, line in enumerate(lines):
            if line.startswith("!") or line.startswith("l.") or "Error" in line:
                picked.extend(lines[i:i + 3])
        text = "\n".join(picked) if picked else "\n".join(lines[-40:])
        if stderr and stderr.strip():
            text = f"{text}\n{stderr.strip()}"
        return text[:max_chars]

    def _fix_with_gpt4o(self, code: str, question: str, errors: list) -> str:
        """使用 GPT-4o 根据编译错误修复代码"""
        if not self.use_gpt4o or not self.client:
            return code

        prompt = f"""You are a code design expert. Fix the following LaTeX/DOT code based on the error messages.

Question: {question}

Code with errors:
{code}

Error messages:
{' '.join(errors)}

Output the corrected code directly, without any explanation:"""

        response = self.client.chat.completions.create(
            model=self.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        return self._extract_code(response.choices[0].message.content)

    def _verify_with_gpt4o(self, code: str, question: str) -> dict:
        """GPT-4o 语义完整性验证"""
        if not self.client:
            return {"is_complete": True, "suggestions": None}
        prompt = f"""You are an expert in code validation. Check if the following diagram code is complete and correct.

Question: {question}

Code:
{code}

Check for:
1. All required elements from the question are present
2. No syntax errors or logical inconsistencies
3. Proper styling and formatting

If errors exist, explain the issues and suggest specific changes.
If no errors, respond with 'The code is correct'.

Validation:"""

        response = self.client.chat.completions.create(
            model=self.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        content = response.choices[0].message.content

        return {
            "is_complete": "The code is correct" in content,
            "suggestions": content if "The code is correct" not in content else None
        }

    def _extract_code(self, text: str) -> str:
        import re
        match = re.search(r'```(?:latex|tikz|dot)?\n(.*?)```', text, re.DOTALL)
        if match:
            return match.group(1)
        return text.strip()

    def _apply_suggestions(self, code: str, suggestions: str) -> str:
        """根据 GPT-4o 建议修改代码"""
        if not self.client or not suggestions or not str(suggestions).strip():
            return code

        prompt = f"""You are a code design expert. Rewrite the diagram code so that it satisfies the review suggestions below.

Review suggestions:
{suggestions}

Code:
{code}

Output the corrected code directly, without any explanation:"""

        response = self.client.chat.completions.create(
            model=self.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        revised = self._extract_code(response.choices[0].message.content or "")
        return revised.strip() or code
