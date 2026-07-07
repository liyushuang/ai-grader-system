"""
Volcano Ark (火山引擎) 批改策略实现

基于字节跳动火山引擎 Ark 平台的多模态模型，
使用 OpenAI 兼容 API 格式。
支持模型：
  - doubao-vision-pro-32k-250115
  - doubao-vision-lite-32k-250115
  - doubao-1.5-vision-pro-32k-250115
  - doubao-1.5-vision-lite-32k-250115
  - Doubao-Seed-2.1-pro
  - 可通过 VOLCANO_MODEL 指定方舟后台的实际 endpoint/model id
"""

import json
import time
import base64
import re
import sys
import os
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grader_base import (
    GradingStrategy, GradingInput, GradingResult,
    SentenceAnalysis, ErrorItem, BoundingBox,
    ErrorType, Confidence, GradingStatus,
    GradingException, APIException, ParseException,
)


class VolcanoGrader(GradingStrategy):
    """
    使用火山引擎 Ark 进行端到端批改。
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "",
        temperature: float = 0.1,
        max_tokens: int = 8192,
        max_retries: int = 1,
        timeout_seconds: int = 600,
    ):
        self.api_key = api_key or os.environ.get("VOLCANO_API_KEY", "")
        self.base_url = base_url
        self.model = model or os.environ.get("VOLCANO_MODEL", "doubao-seed-2-1-pro-260628")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    # ── 接口属性 ──────────────────────────────────────

    @property
    def name(self) -> str:
        return f"Volcano Ark ({self.model})"

    @property
    def supports_bbox(self) -> bool:
        return True

    # ── 主入口 ────────────────────────────────────────

    def grade(self, grading_input: GradingInput) -> GradingResult:
        start_time = time.time()

        try:
            image_b64, processed_size = self._load_and_encode_image(grading_input)
            system_prompt = self._build_system_prompt(grading_input)
            user_content = self._build_user_content(grading_input, image_b64)

            raw_response, token_usage = self._call_api(
                system_prompt, user_content
            )
            result = self._parse_response(raw_response, grading_input, processed_size)
            result = self._post_process(result)
            result.grader_name = self.name
            result.token_usage = token_usage

        except GradingException:
            raise
        except Exception as e:
            raise APIException(
                f"Volcano Ark 批改异常: {e}", self.name, cause=e
            )

        result.processing_time_ms = int((time.time() - start_time) * 1000)
        return result

    # ── 验证 ──────────────────────────────────────────

    def validate(self) -> Tuple[bool, str]:
        if not self.api_key:
            return False, "Volcano Ark API Key 未配置"
        return True, ""

    # ── 图片处理 ──────────────────────────────────────

    def _load_and_encode_image(self, inp: GradingInput) -> Tuple[str, Tuple[int, int]]:
        import io
        from PIL import Image

        if inp.image_data:
            raw = inp.image_data
        elif inp.image_path:
            with open(inp.image_path, "rb") as f:
                raw = f.read()
        else:
            raise GradingException("未提供图片数据(image_data或image_path)")

        img = Image.open(io.BytesIO(raw))
        orig_size = img.size
        print(f"   原图: {orig_size[0]}x{orig_size[1]}, {len(raw)//1024}KB (不压缩)")
        return base64.b64encode(raw).decode("utf-8"), orig_size

    # ── Prompt 构建 ───────────────────────────────────

    def _build_system_prompt(self, inp: GradingInput) -> str:
        """构建系统提示词"""
        from qwen_vl_max_grader import QwenVLMaxGrader
        qwen = QwenVLMaxGrader()
        return qwen._build_system_prompt(inp)

    def _build_user_content(self, inp: GradingInput, image_b64: str) -> list:
        """构建 User Message（文字 + 图片）"""
        return [
            {
                "type": "text",
                "text": f"请批改以下学生提交的《{inp.textbook_name}》文言文翻译作业。仔细识别图片中的手写文字，与标准译文逐句对照，找出所有错误并标注位置。"
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}",
                    "detail": "high"
                }
            }
        ]

    def _uses_responses_api(self, model: str) -> bool:
        normalized = (model or "").lower()
        return "doubao-seed" in normalized or "seed-2-1" in normalized

    def _to_responses_input(self, user_content: list) -> list:
        content = []
        for item in user_content:
            if item.get("type") == "text":
                content.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                image_url = item.get("image_url", {}).get("url", "")
                content.append({"type": "input_image", "image_url": image_url})
        return [{"role": "user", "content": content}]

    def _extract_responses_text(self, payload: dict) -> str:
        if payload.get("output_text"):
            return payload["output_text"]

        parts = []
        for item in payload.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []) or []:
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))
        return "".join(parts)

    def _call_responses_api(self, model: str, system_prompt: str, user_content: list) -> Tuple[str, dict]:
        import requests

        endpoint = self.base_url.rstrip("/") + "/responses"
        payload = {
            "model": model,
            "instructions": system_prompt,
            "input": self._to_responses_input(user_content),
            "max_output_tokens": self.max_tokens,
        }
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise APIException(
                f"Volcano Responses API 调用失败: HTTP {response.status_code} {response.text[:500]}",
                self.name,
            )

        data = response.json()
        usage_data = data.get("usage") or {}
        usage = {
            "prompt_tokens": usage_data.get("input_tokens", 0),
            "completion_tokens": usage_data.get("output_tokens", 0),
            "total_tokens": usage_data.get("total_tokens", 0),
        }
        text = self._extract_responses_text(data)
        if not text.strip():
            reason = (data.get("incomplete_details") or {}).get("reason", "empty_output")
            raise APIException(
                f"Volcano Responses API 未返回正文，status={data.get('status')}，reason={reason}，"
                f"output_tokens={usage.get('completion_tokens', 0)}",
                self.name,
            )
        return text, usage

    # ── API 调用 ──────────────────────────────────────

    def _call_api(self, system_prompt: str, user_content: list) -> Tuple[str, dict]:
        import time as _time

        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        )

        last_error = None
        for model in self._model_candidates():
            for attempt in range(self.max_retries + 1):
                try:
                    print(f"   [Volcano] 使用模型/Endpoint: {model}")
                    self.model = model
                    if self._uses_responses_api(model):
                        return self._call_responses_api(model, system_prompt, user_content)

                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )

                    raw = response.choices[0].message.content or ""
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                    return raw, usage

                except Exception as e:
                    last_error = e
                    if self._is_model_not_found_error(e):
                        print(f"   [Volcano] 模型不可用，尝试下一个: {model}")
                        break
                    if attempt < self.max_retries:
                        wait = 2 ** attempt
                        print(f"   API调用失败，{wait}秒后重试...({e})")
                        _time.sleep(wait)
                        continue
                    raise APIException(
                        f"Volcano Ark API 调用失败(已重试{self.max_retries}次): {e}",
                        self.name, cause=e
                    )

        raise APIException(
            f"Volcano Ark API 调用失败: 所有模型/Endpoint 都不可用，最后错误: {last_error}",
            self.name, cause=last_error
        )

    # ── 流式 API 调用 ─────────────────────────────────

    def _call_api_stream(self, system_prompt: str, user_content: list):
        """
        流式调用 Ark API，逐 token 返回。

        Yields:
            dict: {"type": "llm_chunk", "text": "..."} 或
                  {"type": "llm_done", "raw": "完整文本", "usage": {...}}
        """
        import time as _time

        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        except Exception as e:
            yield {"type": "llm_error", "message": f"OpenAI兼容客户端初始化失败: {e}"}
            return

        last_error = None
        for model in self._model_candidates():
            for attempt in range(self.max_retries + 1):
                try:
                    print(f"   [Volcano] 使用模型/Endpoint: {model}")
                    self.model = model
                    if self._uses_responses_api(model):
                        raw, usage = self._call_responses_api(model, system_prompt, user_content)
                        if raw:
                            yield {"type": "llm_chunk", "text": raw}
                        yield {"type": "llm_done", "raw": raw, "usage": usage}
                        return

                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        stream=True,
                        stream_options={"include_usage": True},
                    )

                    full_text = ""
                    usage = {}
                    for chunk in response:
                        if chunk.choices and chunk.choices[0].delta.content:
                            text = chunk.choices[0].delta.content
                            full_text += text
                            yield {"type": "llm_chunk", "text": text}
                        if hasattr(chunk, 'usage') and chunk.usage:
                            usage = {
                                "prompt_tokens": chunk.usage.prompt_tokens or 0,
                                "completion_tokens": chunk.usage.completion_tokens or 0,
                                "total_tokens": chunk.usage.total_tokens or 0,
                            }

                    yield {"type": "llm_done", "raw": full_text, "usage": usage}
                    return

                except Exception as e:
                    last_error = e
                    if self._is_model_not_found_error(e):
                        yield {"type": "llm_retry", "message": f"模型/Endpoint不可用，尝试下一个：{model}"}
                        break
                    if attempt < self.max_retries:
                        wait = 2 ** attempt
                        yield {"type": "llm_retry", "message": f"API调用失败，{wait}秒后重试...({e})"}
                        _time.sleep(wait)
                        continue
                    yield {"type": "llm_error", "message": f"API调用失败(已重试{self.max_retries}次): {e}"}
                    return

        yield {
            "type": "llm_error",
            "message": f"所有火山模型/Endpoint 都不可用。可在 VOLCANO_MODEL 中填方舟后台实际 Endpoint ID。最后错误: {last_error}"
        }

    def _model_candidates(self) -> list:
        env_model = os.environ.get("VOLCANO_MODEL", "").strip()
        raw = env_model or self.model or ""
        candidates = []
        if raw:
            candidates.extend([m.strip() for m in raw.split(",") if m.strip()])
        candidates.extend([
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2-1-pro-250528",
            "doubao-seed-2-1-pro",
            "Doubao-Seed-2.1-pro",
            "doubao-1-5-vision-pro-32k-250115",
        ])
        deduped = []
        for item in candidates:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _is_model_not_found_error(self, error: Exception) -> bool:
        text = str(error)
        return (
            "InvalidEndpointOrModel.NotFound" in text
            or "does not exist or you do not have access" in text
        )

    # ── 响应解析 ──────────────────────────────────────

    def _parse_response(self, raw: str, inp: GradingInput,
                         image_size: Tuple[int, int] = None) -> GradingResult:
        from qwen_vl_max_grader import QwenVLMaxGrader
        qwen = QwenVLMaxGrader()
        return qwen._parse_response(raw, inp, image_size)

    # ── 后处理 ────────────────────────────────────────

    def _post_process(self, result: GradingResult) -> GradingResult:
        from qwen_vl_max_grader import QwenVLMaxGrader
        qwen = QwenVLMaxGrader()
        return qwen._post_process(result)

    # ── 工具方法 ──────────────────────────────────────

    def _extract_json(self, text: str) -> str:
        from qwen_vl_max_grader import QwenVLMaxGrader
        qwen = QwenVLMaxGrader()
        return qwen._extract_json(text)
