"""
生成模拟学生作业图片（用于 PoC 测试）

生成一张《小石潭记》翻译作业的模拟图片，
包含手写体文字和若干错误，用于验证批改框架。
"""

from PIL import Image, ImageDraw, ImageFont
import os


def generate_sample_homework(output_path: str = "sample_homework.jpg"):
    """生成模拟学生作业图片"""
    
    # 画布尺寸（A4比例，竖版）
    W, H = 800, 1100
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # 加载字体
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zen.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    font_path = None
    for fp in font_paths:
        if os.path.exists(fp):
            font_path = fp
            break
    
    if font_path:
        title_font = ImageFont.truetype(font_path, 24)
        text_font = ImageFont.truetype(font_path, 18)
        small_font = ImageFont.truetype(font_path, 14)
    else:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    
    # 绘制标题
    draw.text((W//2 - 120, 30), "《小石潭记》翻译作业", 
              fill=(30, 30, 30), font=title_font)
    draw.text((W//2 - 80, 60), "姓名：张三    班级：七(2)班", 
              fill=(100, 100, 100), font=small_font)
    
    # 绘制分隔线
    draw.line([(50, 90), (W-50, 90)], fill=(200, 200, 200), width=1)
    
    # 学生翻译内容（包含模拟错误）
    y = 120
    line_height = 32
    
    # 原文标注
    draw.text((50, y), "【原文】从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之。", 
              fill=(150, 150, 150), font=small_font)
    y += 25
    
    # 第1句翻译（正确）
    draw.text((50, y), "从小丘向西走一百二十步，隔着竹林，听到水声，", 
              fill=(30, 30, 30), font=text_font)
    y += line_height
    draw.text((50, y), "好像玉佩玉环碰撞的声音，心里很高兴。", 
              fill=(30, 30, 30), font=text_font)
    y += line_height + 10
    
    # 原文标注
    draw.text((50, y), "【原文】伐竹取道，下见小潭，水尤清冽。", 
              fill=(150, 150, 150), font=small_font)
    y += 25
    
    # 第2句翻译（含错误1："攻打"应为"砍伐"）
    draw.text((50, y), "于是", fill=(30, 30, 30), font=text_font)
    # 错误文字用红色标记（模拟学生写错）
    draw.text((90, y), "攻打", fill=(200, 50, 50), font=text_font)  # 红色错误
    draw.text((130, y), "竹子取得道路，往下看见一个小潭，", 
              fill=(30, 30, 30), font=text_font)
    y += line_height
    draw.text((50, y), "潭水格外清凉。", fill=(30, 30, 30), font=text_font)
    y += line_height + 10
    
    # 原文标注
    draw.text((50, y), "【原文】全石以为底，近岸卷石底以出，为坻，为屿，为嵁，岩。", 
              fill=(150, 150, 150), font=small_font)
    y += 25
    
    # 第3句翻译（含错误2：漏译"为"字）
    draw.text((50, y), "潭以整块石头为底，靠近岸边石底翻卷过来露出水面，", 
              fill=(30, 30, 30), font=text_font)
    y += line_height
    draw.text((50, y), "成为坻、屿、嵁、", fill=(30, 30, 30), font=text_font)
    # 错误：漏了"为"字
    draw.text((200, y), "岩", fill=(200, 50, 50), font=text_font)  # 红色错误
    draw.text((220, y), "各种形态。", fill=(30, 30, 30), font=text_font)
    y += line_height + 10
    
    # 原文标注
    draw.text((50, y), "【原文】青树翠蔓，蒙络摇缀，参差披拂。", 
              fill=(150, 150, 150), font=small_font)
    y += 25
    
    # 第4句翻译（正确且优美）
    draw.text((50, y), "青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，", 
              fill=(30, 30, 30), font=text_font)
    y += line_height
    draw.text((50, y), "参差不齐随风飘拂。", fill=(30, 30, 30), font=text_font)
    y += line_height + 10
    
    # 原文标注
    draw.text((50, y), "【原文】潭中鱼可百许头，皆若空游无所依。", 
              fill=(150, 150, 150), font=small_font)
    y += 25
    
    # 第5句翻译（含错误3："一百多条"应为"一百来条"）
    draw.text((50, y), "潭中鱼大约", fill=(30, 30, 30), font=text_font)
    # 错误
    draw.text((140, y), "一百多条", fill=(200, 50, 50), font=text_font)
    draw.text((220, y), "，都好像在空中游动没有什么依托。", 
              fill=(30, 30, 30), font=text_font)
    y += line_height + 10
    
    # 底部
    draw.line([(50, H-60), (W-50, H-60)], fill=(200, 200, 200), width=1)
    draw.text((W//2 - 100, H-40), "2026年7月6日    第 1 页", 
              fill=(150, 150, 150), font=small_font)
    
    # 保存
    img.save(output_path, "JPEG", quality=95)
    print(f"✅ 模拟作业图片已生成: {output_path}")
    return output_path


if __name__ == "__main__":
    generate_sample_homework("/workspace/poc_grader/output/sample_homework.jpg")
