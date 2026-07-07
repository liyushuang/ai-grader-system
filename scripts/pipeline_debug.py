#!/usr/bin/env python3
"""Run staged grading diagnostics for local test images."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "graders"))

import web_server  # noqa: F401 - loads local PoC API defaults
from grader_base import BoundingBox, GradingInput
from baidu_ocr_grader import OCRLine
from fusion_grader import FusionGrader
from utils.annotation_utils import generate_annotations_from_result


def is_teacher_marked(path: Path) -> bool:
    return "已点评" in path.name


def cache_key(path: Path) -> str:
    digest = hashlib.sha1()
    digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def ocr_cache_path(path: Path) -> Path:
    return ROOT / "output" / "debug" / "cache" / f"{path.stem}_{cache_key(path)}_ocr.json"


def serialize_ocr_lines(ocr_lines: list) -> list:
    return [
        {
            "text": line.text,
            "bbox": line.bbox.to_list() if line.bbox else None,
            "confidence_avg": getattr(line, "confidence_avg", 0.0),
        }
        for line in ocr_lines
    ]


def deserialize_ocr_lines(rows: list) -> list:
    return [
        OCRLine(
            text=row.get("text", ""),
            bbox=BoundingBox.from_list(row.get("bbox")),
            confidence_avg=row.get("confidence_avg", 0.0),
        )
        for row in rows
    ]


def load_or_run_ocr(grader: FusionGrader, inp: GradingInput, path: Path, use_cache: bool):
    cache_path = ocr_cache_path(path)
    if use_cache and cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return deserialize_ocr_lines(data["ocr_lines"]), data["full_text"], "cache"

    ocr_lines, full_text = grader._run_baidu_ocr(inp)
    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "image": path.name,
            "full_text": full_text,
            "ocr_lines": serialize_ocr_lines(ocr_lines),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return ocr_lines, full_text, "live"


def run_one(path: Path, include_llm: bool, use_cache: bool, llm_timeout: int) -> dict:
    grader = FusionGrader(
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        baidu_api_key=os.environ.get("BAIDU_API_KEY", ""),
        baidu_secret_key=os.environ.get("BAIDU_SECRET_KEY", ""),
        llm_provider="qwen",
        max_tokens=4096,
        llm_timeout_seconds=llm_timeout,
    )
    inp = GradingInput(image_path=str(path), textbook_name="小石潭记", textbook_author="柳宗元")

    ocr_lines, full_text, ocr_source = load_or_run_ocr(grader, inp, path, use_cache)
    rule_analyses, clean_lines, segments, aligned, debug = grader._run_rule_pipeline(inp, ocr_lines, full_text)

    report = {
        "image": path.name,
        "teacher_marked": is_teacher_marked(path),
        "used_for_grading": not is_teacher_marked(path),
        "ocr_source": ocr_source,
        "ocr_line_count": len(ocr_lines),
        "clean_body_line_count": len([l for l in clean_lines if not l.skipped]),
        "aligned_segment_count": len(aligned),
        "segments_with_text": len([a for a in aligned if a.student_text]),
        "needs_review_count": len([a for a in aligned if a.needs_review]),
        "rule_error_count": sum(len(sa.errors) for sa in rule_analyses),
        "high_confidence_rule_count": len([
            e for sa in rule_analyses for e in sa.errors if grader._is_high_confidence_rule(e)
        ]),
        "debug": debug,
    }

    if include_llm and not is_teacher_marked(path):
        try:
            pre = grader._build_pre_judgment(rule_analyses, aligned)
            llm_result = grader._run_llm_final(inp, full_text, pre)
            result = grader._fuse_results(rule_analyses, ocr_lines, llm_result, inp, 0)
            grader._preserve_high_confidence_rules(result, rule_analyses)
            annotations = generate_annotations_from_result(result)
            report["final"] = {
                "total_score": result.total_score,
                "total_errors": result.total_errors,
                "dimension_scores": result.dimension_scores,
                "annotation_count": len(annotations),
                "locatable_error_count": len([
                    e for sa in result.sentence_analyses for e in sa.errors if e.bbox
                ]),
                "unlocatable_error_count": len([
                    e for sa in result.sentence_analyses for e in sa.errors if not e.bbox
                ]),
                "errors": [
                    {
                        "sentence_index": si,
                        "original_text": e.original_text,
                        "correct_text": e.correct_text,
                        "reason": e.reason,
                        "bbox": e.bbox.to_list() if e.bbox else None,
                        "anchor_ids": getattr(e, "anchor_ids", []),
                    }
                    for si, sa in enumerate(result.sentence_analyses)
                    for e in sa.errors
                ],
            }
        except Exception as exc:
            report["final_error"] = str(exc)

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="test_data", help="Image file or directory")
    parser.add_argument("--output", default="output/debug/pipeline_debug_report.json")
    parser.add_argument("--include-llm", action="store_true", help="Also call Qwen text review")
    parser.add_argument("--cache", action="store_true", help="Reuse OCR cache")
    parser.add_argument("--llm-timeout", type=int, default=45, help="Qwen text review timeout seconds")
    args = parser.parse_args()

    target = Path(args.input)
    if target.is_dir():
        images = sorted(p for p in target.glob("*.jpg"))
    else:
        images = [target]

    reports = [
        run_one(path, args.include_llm, use_cache=args.cache, llm_timeout=args.llm_timeout)
        for path in images
    ]
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
