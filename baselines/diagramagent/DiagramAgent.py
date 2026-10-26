# diagram_agent_pipeline.py
import os

from baselines.diagramagent.PlanAgent import PlanAgent
from baselines.diagramagent.CodeAgent import CodeAgent
from baselines.diagramagent.DiagramToCodeAgent import DiagramToCodeAgent
from baselines.diagramagent.CheckAgent import CheckAgent

class DiagramAgent:
    def __init__(self, use_gpt4o: bool = True):
        self.plan_agent = PlanAgent()
        self.code_agent = CodeAgent(model_path="DiagramAgent/Code_Agent")
        self.d2c_agent = None
        if (os.getenv("DIAGRAMAGENT_ENABLE_D2C") or "0") != "0":
            self.d2c_agent = DiagramToCodeAgent(model_path="DiagramAgent/Diagram_to_Code_Agent")
        self.check_agent = CheckAgent(use_gpt4o=use_gpt4o)

    def generate(self, query: str, max_retries: int = 3) -> dict:
        """Diagram Generation Task"""
        # 1. Plan: 扩展查询
        expanded_query = self.plan_agent.expand_query(query, task_type="generation")

        # 2. Code: 生成代码
        code = self.code_agent.generate_code(expanded_query, task="generation")

        # 3. Check: 编译验证 + 语义检查
        result = self.check_agent.check(code, expanded_query, code_type=self._detect_type(code))

        # 4. 若失败，重试
        retries = 0
        while not result["success"] and retries < max_retries:
            # 根据错误反馈重新生成
            error_msg = "\n".join(result["errors"])
            code = self.code_agent.generate_code(
                f"{expanded_query}\nPrevious attempt failed with errors: {error_msg}",
                task="generation"
            )
            result = self.check_agent.check(code, expanded_query, code_type=self._detect_type(code))
            retries += 1

        return result

    def edit(self, original_code: str, edit_query: str) -> dict:
        """Diagram Editing Task"""
        # 直接调用 Code Agent 的 editing 功能
        modified_code = self.code_agent.generate_code(edit_query, original_code=original_code, task="editing")
        return self.check_agent.check(modified_code, edit_query, code_type=self._detect_type(modified_code))

    def code_from_image(self, image_path: str, diagram_type: str) -> dict:
        """Diagram Coding Task"""
        # 1. Diagram-to-Code: 图像转代码
        if self.d2c_agent is None:
            return {"success": False, "code": "", "errors": ["d2c_agent_disabled"], "image_path": None}
        code = self.d2c_agent.convert(image_path, diagram_type)

        # 2. Check: 验证
        return self.check_agent.check(code, f"Convert {diagram_type} to code", code_type=self._detect_type(code))

    def _detect_type(self, code: str) -> str:
        if "\\documentclass" in code or "\\begin{tikzpicture}" in code:
            return "tikz"
        elif "digraph" in code or "graph" in code:
            return "dot"
        return "tikz"
