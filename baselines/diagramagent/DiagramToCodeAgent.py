# diagram_to_code_agent.py
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from PIL import Image
import torch

class DiagramToCodeAgent:
    def __init__(self, model_path="DiagramAgent/Diagram_to_Code_Agent", device="cuda"):
        # 加载开源的 Diagram-to-Code Agent 权重（基于 Qwen2-VL）
        self.processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True
        )
        self.device = device

    def convert(self, image_path: str, diagram_type: str = "flowchart") -> str:
        """将图表图像转换为 TikZ/DOT 代码"""
        image = Image.open(image_path).convert("RGB")

        prompt = f"""Convert this {diagram_type} diagram image to complete, compilable LaTeX TikZ code.
Ensure all nodes, edges, labels, and styling are accurately captured."""

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt}
                ]
            }
        ]

        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=[image], return_tensors="pt", padding=True).to(self.device)

        outputs = self.model.generate(
            **inputs,
            max_new_tokens=4096,
            temperature=0.7
        )
        code = self.processor.batch_decode(outputs, skip_special_tokens=True)[0]
        return self._clean_output(code)

    def _clean_output(self, text: str) -> str:
        """清理输出，提取代码"""
        # 类似 CodeAgent 的提取逻辑
        import re
        code_match = re.search(r'\\documentclass.*?\\end{document}', text, re.DOTALL)
        if code_match:
            return code_match.group(0)
        return text.strip()
