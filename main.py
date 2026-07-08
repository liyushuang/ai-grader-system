"""
主入口 — 一键运行批改 PoC

用法：
    python main.py --image <图片路径> --grader <策略名> --output <输出路径>

示例：
    # 使用 Mock 数据（无需API，快速验证渲染效果）
    python main.py --image sample.jpg --grader mock --output result.jpg

    # 使用 Qwen-VL-Max（需要配置 API Key）
    export DASHSCOPE_API_KEY="sk-xxx"
    python main.py --image sample.jpg --grader qwen --output result.jpg
"""

import os
import sys
import json
import argparse
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "graders"))
sys.path.insert(0, str(PROJECT_ROOT / "renderers"))

from utils.env_loader import DEFAULT_ARK_BASE_URL, DEFAULT_ARK_MODEL, load_local_env, normalize_ark_env
from grader_base import GradingInput, GradingResult

load_local_env(PROJECT_ROOT)


def get_grader(name: str):
    """根据名称获取批改策略实例"""
    name_lower = name.lower()
    
    if name_lower in ("mock", "mock_grader", "模拟"):
        from mock_grader import MockGrader
        return MockGrader()
    
    elif name_lower in ("qwen", "qwen-vl-max", "qwen_vl_max", "通义千问"):
        from qwen_vl_max_grader import QwenVLMaxGrader
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            print("⚠️ 警告: DASHSCOPE_API_KEY 环境变量未设置，Qwen-VL-Max 将无法调用")
            print("   请设置: export DASHSCOPE_API_KEY='sk-xxx'")
        return QwenVLMaxGrader(api_key=api_key, timeout_seconds=300, max_retries=1)
    
    elif name_lower in ("baidu", "baidu_ocr", "百度", "百度ocr", "百度手写"):
        from baidu_ocr_grader import BaiduOCRGrader
        api_key = os.environ.get("BAIDU_API_KEY", "")
        secret_key = os.environ.get("BAIDU_SECRET_KEY", "")
        if not api_key or not secret_key:
            print("⚠️ 警告: BAIDU_API_KEY / BAIDU_SECRET_KEY 环境变量未设置")
            print("   请设置: export BAIDU_API_KEY='xxx' BAIDU_SECRET_KEY='xxx'")
        return BaiduOCRGrader(api_key=api_key, secret_key=secret_key, max_retries=2, timeout_seconds=60)
    
    elif name_lower in ("fusion", "融合", "融合批改", "混合"):
        from fusion_grader import FusionGrader
        dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
        baidu_key = os.environ.get("BAIDU_API_KEY", "")
        baidu_secret = os.environ.get("BAIDU_SECRET_KEY", "")
        volcano_key = os.environ.get("VOLCANO_API_KEY", "")
        return FusionGrader(
            dashscope_api_key=dashscope_key,
            baidu_api_key=baidu_key,
            baidu_secret_key=baidu_secret,
            volcano_api_key=volcano_key,
            llm_provider="qwen",
        )
    
    elif name_lower in ("ark_code", "ark-code", "ark", "方舟", "方舟新模型"):
        from fusion_grader import FusionGrader
        dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
        baidu_key = os.environ.get("BAIDU_API_KEY", "")
        baidu_secret = os.environ.get("BAIDU_SECRET_KEY", "")
        ark_base_url, ark_model = normalize_ark_env()
        ark_key = os.environ.get("ARK_API_KEY", "") or os.environ.get("VOLCANO_API_KEY", "")
        if not ark_key:
            print("⚠️ 警告: ARK_API_KEY 环境变量未设置，方舟新模型将无法调用")
            print("   请设置: export ARK_API_KEY='你的方舟专属API Key'")
        return FusionGrader(
            dashscope_api_key=dashscope_key,
            baidu_api_key=baidu_key,
            baidu_secret_key=baidu_secret,
            ark_api_key=ark_key,
            ark_base_url=ark_base_url,
            llm_provider="ark",
            model=ark_model,
        )
    
    else:
        raise ValueError(f"不支持的批改策略: {name}。可用: mock, qwen, baidu, fusion, ark_code")


def run_grading(image_path: str, grader_name: str, output_path: str = None):
    """
    执行完整批改流程。
    
    Returns:
        dict: 包含 result, output_path, json_path
    """
    # 1. 加载批改策略
    print(f"🎯 使用批改策略: {grader_name}")
    grader = get_grader(grader_name)
    
    # 验证策略可用性
    ok, msg = grader.validate()
    if not ok:
        print(f"❌ 策略验证失败: {msg}")
        return None
    
    # 2. 构建输入
    print(f"📷 加载图片: {image_path}")
    if not os.path.exists(image_path):
        print(f"❌ 图片不存在: {image_path}")
        return None
    
    grading_input = GradingInput(
        image_path=image_path,
        textbook_name="小石潭记",
        textbook_author="柳宗元",
    )
    
    # 3. 执行批改
    print(f"⏳ 正在批改...")
    result = grader.grade(grading_input)
    
    print(f"✅ 批改完成!")
    print(f"   {result.summary()}")
    
    # 4. 渲染批改完成图
    if output_path is None:
        output_path = str(PROJECT_ROOT / "output" / "graded_result.jpg")
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    from grading_renderer import GradingRenderer
    renderer = GradingRenderer()
    
    print(f"🎨 渲染批改完成图...")
    renderer.render(image_path, result, output_path)
    print(f"   输出: {output_path}")
    
    # 5. 保存 JSON 报告
    json_path = output_path.replace(".jpg", "_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "grader": result.grader_name,
            "total_score": result.total_score,
            "total_errors": result.total_errors,
            "total_deductions": result.total_deductions,
            "confidence": result.confidence.value,
            "status": result.status.value,
            "processing_time_ms": result.processing_time_ms,
            "overall_comment": result.overall_comment,
            "overall_comment_general": result.overall_comment_general,
            "overall_comment_encouraging": result.overall_comment_encouraging,
            "overall_comment_instructive": result.overall_comment_instructive,
            "polished_full_translation": result.polished_full_translation,
            "recognized_text": result.recognized_text,
            "homework_completion": result.homework_completion,
            "dimension_scores": result.dimension_scores,
            "dimension_analysis": result.dimension_analysis,
            "strengths": result.strengths,
            "weaknesses": result.weaknesses,
            "suggestions": result.suggestions,
            "highlight_sentences": result.highlight_sentences,
            "parent_feedback": result.parent_feedback,
            "system_tags": result.system_tags,
            "sentence_analyses": [
                {
                    "original_classical": sa.original_classical,
                    "student_translation": sa.student_translation,
                    "standard_translation": sa.standard_translation,
                    "polished_translation": sa.polished_translation,
                    "sentence_score": sa.sentence_score,
                    "is_excellent": sa.is_excellent,
                    "is_highlight": sa.is_highlight,
                    "highlight_comment": sa.highlight_comment,
                    "errors": [
                        {
                            "error_type": e.error_type.value,
                            "original_text": e.original_text,
                            "correct_text": e.correct_text,
                            "reason": e.reason,
                            "deduction_points": e.deduction_points,
                            "bbox": e.bbox.to_list() if e.bbox else None,
                        }
                        for e in sa.errors
                    ],
                }
                for sa in result.sentence_analyses
            ],
            "token_usage": result.token_usage,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"   报告: {json_path}")
    
    return {
        "result": result,
        "output_path": output_path,
        "json_path": json_path,
    }


def main():
    parser = argparse.ArgumentParser(
        description="AI 批改功能 PoC — 一键批改学生作业",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # Mock 模式（无需API，验证渲染效果）
  python main.py --image sample.jpg --grader mock

  # Qwen-VL-Max 模式（需要 API Key）
  export DASHSCOPE_API_KEY="sk-xxx"
  python main.py --image sample.jpg --grader qwen

  # 方舟入口（融合流程）
  export ARK_API_KEY="your-ark-key"
  python main.py --image sample.jpg --grader ark_code

  # 百度手写OCR 模式（需要百度 API Key）
  export BAIDU_API_KEY="xxx" BAIDU_SECRET_KEY="xxx"
  python main.py --image sample.jpg --grader baidu
        """
    )
    
    parser.add_argument("--image", "-i", required=True, 
                        help="学生作业图片路径")
    parser.add_argument("--grader", "-g", default="mock", 
                        help="批改策略: mock(模拟) / qwen(Qwen-VL-Max) / fusion(融合) / ark_code(方舟) / baidu(百度手写OCR)")
    parser.add_argument("--output", "-o", default=None, 
                        help="输出图片路径（默认: output/graded_result.jpg）")
    
    args = parser.parse_args()
    
    result = run_grading(args.image, args.grader, args.output)
    
    if result:
        print(f"\n🎉 全部完成! 查看结果:")
        print(f"   批改完成图: {result['output_path']}")
        print(f"   JSON 报告: {result['json_path']}")
        return 0
    else:
        print(f"\n❌ 批改失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
