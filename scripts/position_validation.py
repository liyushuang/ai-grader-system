#!/usr/bin/env python3
"""Validate annotation positioning against final error bboxes."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "graders"))

import web_server  # noqa: F401 - load local API defaults/env fallbacks
from grader_base import GradingInput
from fusion_grader import FusionGrader
from utils.annotation_utils import generate_annotations_from_result, annotations_to_dict_list


def is_teacher_marked(path: Path) -> bool:
    return "已点评" in path.name


def bbox_to_list(bbox):
    return bbox.to_list() if bbox else None


def validate_annotation(ann: dict, result) -> dict:
    sid = ann.get("sentence_index")
    eid = ann.get("error_index")
    row = {
        "annotation_id": ann.get("id"),
        "type": ann.get("type"),
        "comment": ann.get("comment", ""),
        "sentence_index": sid,
        "error_index": eid,
        "ok": False,
        "reason": "",
        "annotation": {
            "start_x": ann.get("start_x"),
            "start_y": ann.get("start_y"),
            "end_x": ann.get("end_x"),
            "end_y": ann.get("end_y"),
        },
        "error_bbox": None,
        "anchor_ids": [],
    }

    if ann.get("type") not in ("line", "circle"):
        row["reason"] = "unsupported_annotation_type_for_auto_position"
        return row
    if sid is None or eid is None:
        row["reason"] = "missing_error_link"
        return row
    if sid < 0 or sid >= len(result.sentence_analyses):
        row["reason"] = "sentence_index_out_of_range"
        return row
    errors = result.sentence_analyses[sid].errors
    if eid < 0 or eid >= len(errors):
        row["reason"] = "error_index_out_of_range"
        return row

    err = errors[eid]
    row["error_text"] = err.original_text
    row["error_bbox"] = bbox_to_list(err.bbox)
    row["anchor_ids"] = list(getattr(err, "anchor_ids", []) or [])
    if not err.bbox:
        row["reason"] = "linked_error_has_no_bbox"
        return row
    if not row["anchor_ids"]:
        row["reason"] = "linked_error_has_no_anchor_ids"
        return row

    x_tol = max(4, round((err.bbox.x2 - err.bbox.x1) * 0.08))
    if ann.get("type") == "circle":
        y_tol = max(4, round((err.bbox.y2 - err.bbox.y1) * 0.08))
        checks = [
            ann.get("start_x", 9999) <= err.bbox.x1 + x_tol,
            ann.get("end_x", -9999) >= err.bbox.x2 - x_tol,
            ann.get("start_y", 9999) <= err.bbox.y1 + y_tol,
            ann.get("end_y", -9999) >= err.bbox.y2 - y_tol,
            ann.get("end_x", -9999) > ann.get("start_x", 9999),
            ann.get("end_y", -9999) > ann.get("start_y", 9999),
        ]
        if all(checks):
            row["ok"] = True
            row["reason"] = "ok"
        else:
            row["reason"] = "circle_not_covering_error_bbox"
            row["expected"] = {
                "x1": err.bbox.x1,
                "x2": err.bbox.x2,
                "y1": err.bbox.y1,
                "y2": err.bbox.y2,
                "x_tol": x_tol,
                "y_tol": y_tol,
            }
        return row

    expected_y = int(err.bbox.y1 + max(1, err.bbox.y2 - err.bbox.y1) * 0.68) + 4
    y_tol = 3
    checks = [
        abs(ann.get("start_y", -9999) - expected_y) <= y_tol,
        abs(ann.get("end_y", -9999) - expected_y) <= y_tol,
        ann.get("start_x", -9999) <= err.bbox.x1 + x_tol,
        ann.get("end_x", -9999) >= err.bbox.x2 - x_tol,
        ann.get("end_x", -9999) > ann.get("start_x", 9999),
    ]
    if all(checks):
        row["ok"] = True
        row["reason"] = "ok"
    else:
        row["reason"] = "line_not_aligned_to_error_bbox"
        row["expected"] = {
            "x1": err.bbox.x1,
            "x2": err.bbox.x2,
            "y": expected_y,
            "x_tol": x_tol,
            "y_tol": y_tol,
        }
    return row


def run_one(path: Path, timeout: int) -> dict:
    grader = FusionGrader(
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        baidu_api_key=os.environ.get("BAIDU_API_KEY", ""),
        baidu_secret_key=os.environ.get("BAIDU_SECRET_KEY", ""),
        llm_provider="qwen",
        max_tokens=4096,
        llm_timeout_seconds=timeout,
    )
    inp = GradingInput(image_path=str(path), textbook_name="小石潭记", textbook_author="柳宗元")
    start = time.time()
    result = grader.grade(inp)
    annotations = annotations_to_dict_list(generate_annotations_from_result(result))
    rows = [validate_annotation(ann, result) for ann in annotations]
    ok_count = sum(1 for row in rows if row["ok"])
    return {
        "image": path.name,
        "status": getattr(result.status, "value", str(result.status)),
        "score": result.total_score,
        "total_errors": result.total_errors,
        "annotation_count": len(annotations),
        "ok_count": ok_count,
        "accuracy": 1.0 if not annotations else round(ok_count / len(annotations), 4),
        "duration_ms": int((time.time() - start) * 1000),
        "annotations": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="test_data")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", default="output/debug/position_validation_report.json")
    parser.add_argument("--llm-timeout", type=int, default=60)
    args = parser.parse_args()

    target = Path(args.input)
    images = sorted(target.glob("*.jpg")) if target.is_dir() else [target]
    images = [path for path in images if not is_teacher_marked(path)]

    report = []
    for round_no in range(1, args.rounds + 1):
        round_rows = []
        for image in images:
            round_rows.append(run_one(image, args.llm_timeout))
        total_annotations = sum(row["annotation_count"] for row in round_rows)
        total_ok = sum(row["ok_count"] for row in round_rows)
        report.append({
            "round": round_no,
            "image_count": len(round_rows),
            "annotation_count": total_annotations,
            "ok_count": total_ok,
            "accuracy": 1.0 if total_annotations == 0 else round(total_ok / total_annotations, 4),
            "images": round_rows,
        })

    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    for round_row in report:
        print(
            f"round={round_row['round']} images={round_row['image_count']} "
            f"annotations={round_row['annotation_count']} ok={round_row['ok_count']} "
            f"accuracy={round_row['accuracy']}"
        )


if __name__ == "__main__":
    main()
