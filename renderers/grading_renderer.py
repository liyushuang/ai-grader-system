"""
渲染器 — 仿截图样式生成批改完成图

参考截图样式：
- 左侧：原图 + 红色圆圈标注 + 蓝色序号标签
- 右侧：详细点评列表（序号对应）+ 总评区域
- 底部：分数 + 评语

最小功能闭环：生成一张"左图右评"的批改完成图。
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont
from typing import List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grader_base import GradingResult, ErrorItem, BoundingBox


class GradingRenderer:
    """
    仿截图样式的批改完成图渲染器。
    
    布局：
    ┌────────────────────────────────────────────────────────────┐
    │  左侧：原图区域（60%宽度）                                  │
    │  ├── 原图缩放展示                                          │
    │  ├── 红色圆圈标注错误位置                                   │
    │  └── 蓝色序号标签（①②③...）                               │
    │                                                            │
    │  右侧：点评区域（40%宽度）                                  │
    │  ├── 详细点评列表（红字，带序号）                            │
    │  └── 总评区域（黑字，评语）                                 │
    │                                                            │
    │  底部：分数栏                                               │
    │  └── 红色大号分数 + 评语                                    │
    └────────────────────────────────────────────────────────────┘
    """

    # 颜色配置
    COLOR_RED = (255, 51, 51)           # 错误标注/扣分文字
    COLOR_BLUE = (59, 130, 246)         # 序号标签背景
    COLOR_WHITE = (255, 255, 255)       # 白色
    COLOR_BLACK = (30, 30, 30)          # 正文黑
    COLOR_GRAY = (120, 120, 120)        # 辅助灰
    COLOR_BG = (250, 250, 250)         # 背景灰
    COLOR_BORDER = (220, 220, 220)      # 边框灰
    COLOR_GREEN = (34, 197, 94)         # 正确/亮点

    # 布局参数
    LEFT_RATIO = 0.58       # 左侧原图占比
    RIGHT_RATIO = 0.42      # 右侧点评占比
    PADDING = 30            # 内边距
    GAP = 20              # 元素间距
    
    def __init__(self):
        self.font_large = None
        self.font_medium = None
        self.font_small = None
        self.font_score = None
        self._load_fonts()

    def _load_fonts(self):
        """加载字体（优先使用文泉驿，回退到默认）"""
        font_paths = [
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zen.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        
        font_path = None
        for fp in font_paths:
            if os.path.exists(fp):
                font_path = fp
                break
        
        try:
            if font_path:
                self.font_large = ImageFont.truetype(font_path, 20)
                self.font_medium = ImageFont.truetype(font_path, 16)
                self.font_small = ImageFont.truetype(font_path, 14)
                self.font_score = ImageFont.truetype(font_path, 48)
                self.font_comment = ImageFont.truetype(font_path, 18)
            else:
                self.font_large = ImageFont.load_default()
                self.font_medium = ImageFont.load_default()
                self.font_small = ImageFont.load_default()
                self.font_score = ImageFont.load_default()
                self.font_comment = ImageFont.load_default()
        except Exception:
            self.font_large = ImageFont.load_default()
            self.font_medium = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
            self.font_score = ImageFont.load_default()
            self.font_comment = ImageFont.load_default()

    def render(self, original_image_path: str, result: GradingResult, 
               output_path: str) -> str:
        """
        渲染批改完成图。
        
        Args:
            original_image_path: 原始作业图片路径
            result: 批改结果
            output_path: 输出图片路径
            
        Returns:
            output_path: 输出文件路径
        """
        # 加载原图
        original = Image.open(original_image_path).convert("RGB")
        orig_w, orig_h = original.size
        
        # 计算画布尺寸（固定宽度，高度自适应）
        canvas_w = 1400
        
        # 预估右侧点评区域所需高度
        right_panel_height = self._estimate_right_panel_height(result)
        
        # 左侧图片高度 + 底部栏 + 边距
        left_panel_height = orig_h + 200  # 缩放后
        
        canvas_h = max(1000, right_panel_height + 200, left_panel_height)
        canvas_h = min(canvas_h, 2000)  # 上限防止过大
        
        # 创建画布
        canvas = Image.new("RGB", (canvas_w, canvas_h), self.COLOR_BG)
        draw = ImageDraw.Draw(canvas)
        
        # 左侧区域宽度
        left_w = int(canvas_w * self.LEFT_RATIO)
        right_x = left_w + self.GAP
        
        # 1. 绘制左侧原图区域
        self._draw_left_panel(canvas, draw, original, left_w, result, orig_w, orig_h, canvas_h)
        
        # 2. 绘制右侧点评区域
        self._draw_right_panel(canvas, draw, result, right_x, canvas_w, canvas_h)
        
        # 3. 绘制底部分数栏
        self._draw_score_bar(canvas, draw, result, canvas_w, canvas_h)
        
        # 保存
        canvas.save(output_path, "JPEG", quality=95)
        return output_path

    def _estimate_right_panel_height(self, result: GradingResult) -> int:
        """预估右侧点评区域高度"""
        all_errors = []
        for sa in result.sentence_analyses:
            for err in sa.errors:
                if err.bbox:
                    all_errors.append(err)
        
        # 每个错误约 100px 高度
        return len(all_errors) * 100 + 200

    def _draw_left_panel(self, canvas: Image, draw: ImageDraw, 
                         original: Image, left_w: int, 
                         result: GradingResult,
                         orig_w: int, orig_h: int,
                         canvas_h: int):
        """绘制左侧原图面板（含标注）"""
        # 计算缩放比例，使图片适配左侧区域
        available_w = left_w - self.PADDING * 2
        available_h = canvas_h - self.PADDING * 2 - 120  # 预留底部空间
        
        scale = min(available_w / orig_w, available_h / orig_h)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        
        # 缩放原图
        scaled = original.resize((new_w, new_h), Image.LANCZOS)
        
        # 居中放置
        img_x = self.PADDING + (available_w - new_w) // 2
        img_y = self.PADDING + 40
        
        # 绘制白色背景框
        draw.rectangle(
            [img_x - 5, img_y - 5, img_x + new_w + 5, img_y + new_h + 5],
            fill=self.COLOR_WHITE, outline=self.COLOR_BORDER, width=1
        )
        
        # 粘贴原图
        canvas.paste(scaled, (img_x, img_y))
        
        # 标题
        draw.text((img_x, img_y - 30), "学生作业", 
                  fill=self.COLOR_BLACK, font=self.font_medium)
        
        # 绘制错误标注（红色圆圈 + 蓝色序号）
        self._draw_annotations(canvas, draw, result, img_x, img_y, scale, new_w, new_h)

    def _draw_annotations(self, canvas: Image, draw: ImageDraw,
                          result: GradingResult, img_x: int, img_y: int, 
                          scale: float, new_w: int, new_h: int):
        """在原图上绘制错误标注（红圈 + 序号）"""
        # 收集所有带坐标的错误
        all_errors = []
        for sa in result.sentence_analyses:
            for err in sa.errors:
                if err.bbox:
                    all_errors.append(err)
        
        # 按坐标排序（从上到下）
        all_errors.sort(key=lambda e: e.bbox.y1)
        
        for idx, err in enumerate(all_errors, 1):
            bbox = err.bbox
            
            # 缩放坐标到画布上的位置
            cx = img_x + int(bbox.x1 * scale)
            cy = img_y + int(bbox.y1 * scale)
            cw = int(bbox.width * scale)
            ch = int(bbox.height * scale)
            
            # 绘制半透明红色高亮背景（覆盖错误文字区域，容忍坐标偏差）
            padding = 6
            hl_x1 = max(img_x, cx - padding)
            hl_y1 = max(img_y, cy - padding)
            hl_x2 = min(img_x + new_w, cx + cw + padding)
            hl_y2 = min(img_y + new_h, cy + ch + padding)
            
            # 创建半透明红色叠加层
            overlay = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            overlay_draw.rectangle(
                [hl_x1, hl_y1, hl_x2, hl_y2],
                fill=(255, 51, 51, 50)  # 红色 20% 透明度
            )
            canvas.paste(overlay, (0, 0), overlay)
            
            # 底部红色下划线
            draw.line(
                [(hl_x1, hl_y2), (hl_x2, hl_y2)],
                fill=self.COLOR_RED, width=2
            )
            
            # 蓝色序号标签
            label_radius = 10
            label_x = hl_x1 - 2
            label_y = hl_y1 - 2
            
            # 标签背景圆
            draw.ellipse(
                [label_x - label_radius, label_y - label_radius,
                 label_x + label_radius, label_y + label_radius],
                fill=self.COLOR_BLUE
            )
            
            # 标签文字
            label_text = str(idx)
            bbox_text = draw.textbbox((0, 0), label_text, font=self.font_small)
            tw = bbox_text[2] - bbox_text[0]
            th = bbox_text[3] - bbox_text[1]
            draw.text((label_x - tw//2, label_y - th//2 - 2), 
                      label_text, fill=self.COLOR_WHITE, font=self.font_small)

    def _draw_right_panel(self, canvas: Image, draw: ImageDraw,
                          result: GradingResult, right_x: int, 
                          canvas_w: int, canvas_h: int):
        """绘制右侧点评面板"""
        panel_w = canvas_w - right_x - self.PADDING
        
        # 标题
        draw.text((right_x, self.PADDING), "详细点评", 
                  fill=self.COLOR_BLACK, font=self.font_large)
        
        # 绘制分割线
        draw.line([(right_x, self.PADDING + 30), 
                   (right_x + panel_w, self.PADDING + 30)],
                  fill=self.COLOR_BORDER, width=1)
        
        # 点评列表起始位置
        y = self.PADDING + 45
        
        # 收集所有错误
        all_errors = []
        for sa in result.sentence_analyses:
            for err in sa.errors:
                if err.bbox:
                    all_errors.append(err)
        all_errors.sort(key=lambda e: e.bbox.y1)
        
        for idx, err in enumerate(all_errors, 1):
            # 序号圆圈
            circle_r = 10
            draw.ellipse(
                [right_x, y - circle_r, right_x + circle_r * 2, y + circle_r],
                fill=self.COLOR_BLUE
            )
            draw.text((right_x + 5, y - 8), str(idx), 
                      fill=self.COLOR_WHITE, font=self.font_small)
            
            # 错误类型标签
            type_text = f"[{err.error_type.value}]"
            draw.text((right_x + 28, y - 10), type_text, 
                      fill=self.COLOR_RED, font=self.font_small)
            
            # 错误内容（红色）
            y += 20
            error_line = f"❌ {err.original_text} → ✅ {err.correct_text}"
            draw.text((right_x + 28, y), error_line, 
                      fill=self.COLOR_RED, font=self.font_medium)
            
            # 判定理由（灰色小字）
            y += 22
            reason_lines = self._wrap_text(err.reason, panel_w - 40, self.font_small)
            for line in reason_lines:
                draw.text((right_x + 28, y), line, 
                          fill=self.COLOR_GRAY, font=self.font_small)
                y += 18
            
            # 扣分
            y += 5
            draw.text((right_x + 28, y), f"扣 {err.deduction_points} 分", 
                      fill=self.COLOR_RED, font=self.font_small)
            
            y += 35  # 下一个错误间距
            
            # 防止超出画布
            if y > canvas_h - 150:
                draw.text((right_x, y), "... 更多错误请查看完整报告", 
                          fill=self.COLOR_GRAY, font=self.font_small)
                break
        
        # 如果没有错误
        if not all_errors:
            draw.text((right_x, y), "✅ 未发现明显错误，翻译质量优秀！", 
                      fill=self.COLOR_GREEN, font=self.font_medium)

    def _draw_score_bar(self, canvas: Image, draw: ImageDraw,
                        result: GradingResult, canvas_w: int, canvas_h: int):
        """绘制底部分数栏"""
        bar_h = 110
        bar_y = canvas_h - bar_h
        
        # 背景
        draw.rectangle([0, bar_y, canvas_w, canvas_h], 
                        fill=(245, 245, 245), outline=self.COLOR_BORDER, width=1)
        
        # 左侧：大号分数
        score_x = 40
        score_y = bar_y + 15
        
        # 分数标签
        draw.text((score_x, score_y), "得分", 
                  fill=self.COLOR_GRAY, font=self.font_small)
        
        # 大号分数
        score_text = str(result.total_score)
        draw.text((score_x, score_y + 20), score_text, 
                  fill=self.COLOR_RED, font=self.font_score)
        
        # 分数字
        draw.text((score_x + 80, score_y + 35), "分", 
                  fill=self.COLOR_GRAY, font=self.font_medium)
        
        # 右侧：评语
        comment_x = 200
        comment_y = bar_y + 20
        
        draw.text((comment_x, comment_y), "总评", 
                  fill=self.COLOR_GRAY, font=self.font_small)
        
        # 评语文字（自动换行）
        comment_lines = self._wrap_text(result.overall_comment, 
                                       canvas_w - comment_x - 200, 
                                       self.font_comment)
        for i, line in enumerate(comment_lines):
            draw.text((comment_x, comment_y + 22 + i * 24), line, 
                      fill=self.COLOR_BLACK, font=self.font_comment)
        
        # 置信度标签
        conf_x = canvas_w - 180
        conf_color = self.COLOR_GREEN if result.confidence.value == "高" else self.COLOR_GRAY
        draw.text((conf_x, bar_y + 35), f"置信度: {result.confidence.value}", 
                  fill=conf_color, font=self.font_medium)
        
        # 耗时
        draw.text((conf_x, bar_y + 60), 
                  f"处理耗时: {result.processing_time_ms}ms", 
                  fill=self.COLOR_GRAY, font=self.font_small)
        
        # 批改器名称
        draw.text((conf_x, bar_y + 80), 
                  f"引擎: {result.grader_name}", 
                  fill=self.COLOR_GRAY, font=self.font_small)

    def _wrap_text(self, text: str, max_width: int, font) -> List[str]:
        """文字自动换行"""
        if not text:
            return [""]
        
        # 创建临时 draw 对象用于测量文字宽度
        temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        
        lines = []
        current_line = ""
        
        for char in text:
            test_line = current_line + char
            bbox = temp_draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] > max_width and current_line:
                lines.append(current_line)
                current_line = char
            else:
                current_line = test_line
        
        if current_line:
            lines.append(current_line)
        
        return lines if lines else [""]
