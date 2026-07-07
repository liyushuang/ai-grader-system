"""
本地规则引擎 — 基于标准译文和关键词规则表进行批改

不依赖任何 LLM API，纯本地计算。
用于百度 OCR 方案中的批改环节，也适用于任何需要离线批改的场景。

核心能力：
1. 加载标准译文，按句号/分号/换行分句
2. 将学生 OCR 识别文本与标准译文逐句匹配（编辑距离 + 关键词重叠）
3. 检测错误：只有学生用了明确错误的翻译才扣分
4. 评估置信度，低置信度句可触发 LLM 增强
"""

import re
import sys
import os
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field

# 尝试导入 jieba 分词
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grader_base import (
    SentenceAnalysis, ErrorItem, ErrorType, Confidence, BoundingBox
)


# ── 关键词规则表 ─────────────────────────────────────
# 格式：关键词 → {correct: 正确翻译, errors: [明确错误的翻译], deduction: 扣分, type: 错误类型}
#
# errors 字段只放明确错误的翻译形式。
# 正确的翻译变体（如 "砍掉"→"伐" 的合理变体 "砍伐"）不在 errors 中。
# 这样学生写出合理变体时不会被误扣分。

_KEYWORD_RULES: Dict[str, dict] = {
    # ── 第1句：从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之 ──
    "西":       {"correct": "向西",       "errors": ["西方", "西边", "往西走"],    "deduction": 3, "type": ErrorType.CONTENT_ERROR},
    "小丘":      {"correct": "小丘",       "errors": ["小石丘", "小山丘", "小山坡"],  "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "闻":       {"correct": "听到/听见",   "errors": ["闻见", "嗅到", "闻声"],    "deduction": 2, "type": ErrorType.CONTENT_ERROR},
    "心乐之":    {"correct": "心里很高兴",  "errors": ["心里快乐", "心里喜欢"],     "deduction": 2, "type": ErrorType.CONTENT_ERROR},

    # ── 第2句：伐竹取道，下见小潭，水尤清冽 ──
    "伐":       {"correct": "砍伐/砍掉",   "errors": ["攻打", "讨伐", "征伐", "杀伐"], "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "取道":      {"correct": "开辟道路",    "errors": ["取得道路", "取路", "拿路"],    "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "尤":       {"correct": "格外",        "errors": ["尤其", "犹", "由"],          "deduction": 3, "type": ErrorType.CONTENT_ERROR},
    "清冽":      {"correct": "清凉",        "errors": ["清澈", "清冷", "冷冽", "清齐"], "deduction": 5, "type": ErrorType.CONTENT_ERROR},

    # ── 第3句：全石以为底，近岸卷石底以出，为坻，为屿，为嵁，为岩 ──
    "全石以为底": {"correct": "以整块石头为底", "errors": ["铺满石头为底", "全是石头做底"], "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "卷石底以出": {"correct": "石底翻卷露出水面", "errors": ["卷起石头", "翻出石头"],    "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "为坻":      {"correct": "成为坻（水中高地）", "errors": ["是高地", "成为高地"],    "deduction": 3, "type": ErrorType.CONTENT_ERROR},
    "为嵁":      {"correct": "成为嵁（不平的岩石）", "errors": ["是凸起", "是石头"],    "deduction": 3, "type": ErrorType.CONTENT_ERROR},

    # ── 第4句：青树翠蔓，蒙络摇缀，参差披拂 ──
    "翠蔓":      {"correct": "翠绿的藤蔓",   "errors": ["翠绿的蔓", "绿蔓"],          "deduction": 3, "type": ErrorType.CONTENT_ERROR},
    "披拂":      {"correct": "随风飘拂",     "errors": ["随风摇荡", "摇荡", "摇摆"],   "deduction": 5, "type": ErrorType.CONTENT_ERROR},

    # ── 第5句：潭中鱼可百许头，皆若空游无所依 ──
    "可":       {"correct": "大约",         "errors": ["可以", "可能", "能够"],       "deduction": 3, "type": ErrorType.CONTENT_ERROR},
    "许":       {"correct": "来/左右",       "errors": ["多", "许多", "很多"],        "deduction": 3, "type": ErrorType.CONTENT_ERROR},
    "无所依":    {"correct": "没有依托",      "errors": ["没有依靠", "没有东西靠着", "没什么靠的"], "deduction": 3, "type": ErrorType.CONTENT_ERROR},

    # ── 第6句：日光下澈，影布石上。佁然不动，俶尔远逝，往来翕忽，似与游者相乐 ──
    "下澈":      {"correct": "直照到水底",   "errors": ["往下清澈", "洒下", "照到下面", "往下照"], "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "影布石上":  {"correct": "影子映在石上",  "errors": ["影子印在石上", "影子印在石底上", "影子在石底"], "deduction": 2, "type": ErrorType.CONTENT_ERROR},
    "佁然":      {"correct": "呆呆地",       "errors": ["忽然", "突然", "猛然"],       "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "俶尔":      {"correct": "忽然",         "errors": ["呆呆地", "静止地", "慢慢地"],   "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "翕忽":      {"correct": "轻快敏捷",      "errors": ["疾速", "迅速", "飞快"],       "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "相乐":      {"correct": "相互取乐",      "errors": ["互相玩", "一起玩耍"],         "deduction": 3, "type": ErrorType.CONTENT_ERROR},

    # ── 第7句：潭西南而望，斗折蛇行，明灭可见 ──
    "斗折":      {"correct": "像北斗星那样曲折", "errors": ["弯折", "折弯", "打折"],    "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "蛇行":      {"correct": "像蛇蜿蜒前行",   "errors": ["蛇爬行", "蛇在爬"],         "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "明灭可见":  {"correct": "忽明忽暗",       "errors": ["看得见看不见", "一会亮一会暗"], "deduction": 5, "type": ErrorType.CONTENT_ERROR},

    # ── 第8句：其岸势犬牙差互，不可知其源 ──
    "犬牙差互":  {"correct": "像狗牙参差不齐", "errors": ["犬牙交错", "狗牙交错"],      "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "源":       {"correct": "源头",          "errors": ["来源", "起点"],              "deduction": 3, "type": ErrorType.CONTENT_ERROR},

    # ── 第9句：坐潭上，四面竹树环合，寂寥无人，凄神寒骨，悄怆幽邃 ──
    "环合":      {"correct": "环绕合拢",      "errors": ["围绕", "包围", "环抱"],      "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "凄神寒骨":  {"correct": "心神凄凉寒气透骨", "errors": ["冷到骨头", "骨头冷", "凄冷入骨"], "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "悄怆幽邃":  {"correct": "寂静幽深令人忧伤", "errors": ["悄悄悲伤", "幽深可怕"],     "deduction": 5, "type": ErrorType.CONTENT_ERROR},

    # ── 第10句：以其境过清，不可久居，乃记之而去 ──
    "以":       {"correct": "因为",          "errors": ["用", "拿", "把"],            "deduction": 3, "type": ErrorType.FUNCTION_ERROR},
    "过清":      {"correct": "太冷清",        "errors": ["太清", "过冷", "太冷"],       "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "居":       {"correct": "停留/久留",      "errors": ["居住", "住下", "住在这里"],    "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "乃":       {"correct": "于是/就",        "errors": ["才", "便", "然后"],           "deduction": 3, "type": ErrorType.FUNCTION_ERROR},

    # ── 第11句：同游者：吴武陵，龚古，余弟宗玄。隶而从者，崔氏二小生：曰恕己，曰奉壹 ──
    "同游者":    {"correct": "一同游玩的人",   "errors": ["同游的人", "一起玩的人"],     "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "余弟":      {"correct": "我的弟弟",       "errors": ["弟弟", "我的兄弟"],          "deduction": 3, "type": ErrorType.CONTENT_ERROR},
    "隶而从者":  {"correct": "跟着同去的",      "errors": ["奴隶跟随", "随从人员"],      "deduction": 5, "type": ErrorType.CONTENT_ERROR},
    "二小生":    {"correct": "两个年轻人",      "errors": ["两个小孩", "两个学生", "两个小学生"], "deduction": 5, "type": ErrorType.CONTENT_ERROR},
}


# ── 语义等价表 ─────────────────────────────────────
# 学生写出这些表达方式时，视为正确翻译，不扣分。
# 用于解决规则引擎"无法理解语义等价"的核心缺陷。

_SEMANTIC_EQUIVALENTS: Dict[str, List[str]] = {
    # ── 第1句关键词 ──
    "全石以为底": [
        "铺满石头为底", "以整块石头为底", "潭底全是石头",
        "潭底铺满石头为底", "潭底铺满石头", "潭底全是石头为底",
    ],
    "心乐之": [
        "心里很是快乐", "心里很高兴", "心中很是快乐",
        "心里对此很高兴", "心中为此很快乐", "心里快乐",
        "心中很是快乐",
    ],
    "闻": [
        "听闻", "听到", "听见", "听到了",
    ],
    "小丘": [
        "小石丘",
    ],
    "西": [
        "向西", "往西",
    ],

    # ── 第2句关键词 ──
    "伐": [
        "砍掉", "砍伐",
    ],
    "取道": [
        "开辟出一条出小路", "开辟道路", "开出一条路",
    ],
    "清冽": [
        "清澈", "格外清澈", "犹齐清澈",
    ],
    "尤": [
        "格外", "特别",
    ],

    # ── 第3句关键词 ──
    "卷石底以出": [
        "石底周边向上卷起", "石底翻卷露出水面", "石底向上翻卷",
    ],
    "为坻": [
        "有高地", "成为坻", "成为高地",
    ],
    "为嵁": [
        "有凸起的地方", "成为嵁", "不平的岩石",
    ],
    "为屿": [
        "有小屿", "成为屿",
    ],

    # ── 第4句关键词 ──
    "翠蔓": [
        "翠绿藤蔓", "翠绿的藤蔓", "翠绿大树上垂下翠绿藤蔓",
    ],
    "披拂": [
        "随风飘拂", "随风摇荡", "随风飘摇",
        "参差不齐随风摇荡", "随风飘动", "随风摇摆",
    ],

    # ── 第5句关键词 ──
    "可": [
        "约有", "大约有", "大约",
    ],
    "许": [
        "来", "左右", "约",
    ],
    "无所依": [
        "没有依托", "没有任何东西靠着", "没有依靠",
        "没有任何依托", "没有什么依托", "没有任何东西依靠",
    ],
    "空游": [
        "在空中游动", "仿佛在空中游动",
    ],

    # ── 第6句关键词 ──
    "下澈": [
        "阳光洒在潭水底", "阳光直照到水底", "阳光洒下照到水底",
        "阳光洒下", "阳光直照水底", "阳光洒在潭水底",
    ],
    "影布石上": [
        "影子映在石上", "影子印在石底上", "鱼的影子印在石底上",
        "影子印在石上", "鱼的影子映在石上", "鱼的影子印在石上",
    ],
    "佁然": [
        "鱼儿静止不动", "静止不动", "呆呆地不动",
    ],
    "俶尔": [
        "忽然", "忽然游向远方", "忽然向远处游去",
    ],
    "翕忽": [
        "来去疾速", "疾速", "来去快速", "来来往往快速",
    ],
    "相乐": [
        "和游人互相", "相互取乐", "互相取乐",
    ],

    # ── 第7句关键词 ──
    "斗折": [
        "如北斗星连起那样曲折", "像北斗星那样曲折", "如北斗星曲折",
    ],
    "蛇行": [
        "如长蛇一般弯曲", "像蛇蜿蜒前行", "如蛇一般弯曲",
    ],
    "明灭可见": [
        "时而隐藏时而显现", "忽明忽暗", "时隐时现",
    ],

    # ── 第8句关键词 ──
    "犬牙差互": [
        "犬齿一般交错错", "像狗牙参差不齐", "犬牙交错",
        "狗犬齿一般交错", "如同狗犬齿一般交错错",
    ],
    "源": [
        "源头", "发现源头", "知道它的源头",
    ],

    # ── 第9句关键词 ──
    "环合": [
        "被竹林环绕", "环绕合抱", "四面被竹子和树木环绕",
    ],
    "凄神寒骨": [
        "心里悲伤寒气透骨", "心神凄凉寒气透骨", "悲伤寒气透骨",
        "心里悲伤,寒气透骨",
    ],
    "悄怆幽邃": [
        "凄凉幽深", "寂静幽深令人忧伤", "幽静深远",
    ],

    # ── 第10句关键词 ──
    "以": [
        "因为", "由于",
    ],
    "过清": [
        "太凄清", "太冷清", "过于凄清",
    ],
    "居": [
        "久留", "停留", "久住",
    ],
    "乃": [
        "于是", "就", "便",
    ],
    "不可久居": [
        "不可久住在这", "不可久留", "不能久留", "不可久住",
    ],

    # ── 第11句关键词 ──
    "同游者": [
        "和我一样被贬的还有", "一同游览的人", "同游的人",
    ],
    "余弟": [
        "我弟弟", "我的弟弟",
    ],
    "隶而从者": [
        "跟随着", "跟着同去的", "跟随着同去",
    ],
    "二小生": [
        "两个年轻人", "两个年青人",
    ],
}


# ── 《小石潭记》标准译文（逐句拆分）───────────────────

_STANDARD_SENTENCES = [
    {
        "classical": "从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之。",
        "translation": "从小丘向西走一百二十步，隔着竹林，听到了水声，好像玉佩玉环碰撞发出的声音，心里很高兴。",
        "keywords": ["西", "小丘", "闻", "心乐之"],
    },
    {
        "classical": "伐竹取道，下见小潭，水尤清冽。",
        "translation": "于是砍伐竹林开辟道路，往下看见一个小水潭，潭水格外清凉。",
        "keywords": ["伐", "取道", "尤", "清冽"],
    },
    {
        "classical": "全石以为底，近岸卷石底以出，为坻，为屿，为嵁，为岩。",
        "translation": "潭以整块石头为底，靠近岸边石底翻卷过来露出水面，成为坻、屿、嵁、岩各种形态。",
        "keywords": ["全石以为底", "卷石底以出", "为坻", "为嵁"],
    },
    {
        "classical": "青树翠蔓，蒙络摇缀，参差披拂。",
        "translation": "青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，参差不齐随风飘拂。",
        "keywords": ["翠蔓", "披拂"],
    },
    {
        "classical": "潭中鱼可百许头，皆若空游无所依。",
        "translation": "潭中鱼大约有一百来条，都好像在空中游动没有什么依托。",
        "keywords": ["可", "许", "无所依"],
    },
    {
        "classical": "日光下澈，影布石上。佁然不动，俶尔远逝，往来翕忽，似与游者相乐。",
        "translation": "阳光直照到水底，鱼的影子映在石上。鱼儿静止不动，忽然又向远处游去，来来往往轻快敏捷，好像和游人相互取乐。",
        "keywords": ["下澈", "影布石上", "佁然", "俶尔", "翕忽", "相乐"],
    },
    {
        "classical": "潭西南而望，斗折蛇行，明灭可见。",
        "translation": "向石潭的西南方向望去，溪流像北斗星那样曲折，像蛇那样蜿蜒前行，忽明忽暗。",
        "keywords": ["斗折", "蛇行", "明灭可见"],
    },
    {
        "classical": "其岸势犬牙差互，不可知其源。",
        "translation": "那岸的形状像狗牙那样参差不齐，不能知道它的源头。",
        "keywords": ["犬牙差互", "源"],
    },
    {
        "classical": "坐潭上，四面竹树环合，寂寥无人，凄神寒骨，悄怆幽邃。",
        "translation": "坐在石潭边上，四面竹林树木环绕合拢，寂静寥落空无一人，使人感到心神凄凉寒气透骨，寂静幽深令人忧伤。",
        "keywords": ["环合", "凄神寒骨", "悄怆幽邃"],
    },
    {
        "classical": "以其境过清，不可久居，乃记之而去。",
        "translation": "因为这里的环境太冷清，不能久留，于是记下这番景致就离开了。",
        "keywords": ["以", "过清", "居", "乃"],
    },
    {
        "classical": "同游者：吴武陵，龚古，余弟宗玄。隶而从者，崔氏二小生：曰恕己，曰奉壹。",
        "translation": "一同游玩的人有吴武陵、龚古、我的弟弟宗玄。跟着同去的，有姓崔的两个年轻人，一个叫恕己，一个叫奉壹。",
        "keywords": ["同游者", "余弟", "隶而从者", "二小生"],
    },
]


# ── 辅助：编辑距离 ──────────────────────────────────

def levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串之间的 Levenshtein 编辑距离"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def sentence_similarity(s1: str, s2: str) -> float:
    """
    综合相似度 = 0.4 * Levenshtein归一化 + 0.6 * 关键词重叠率
    """
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    lev_sim = 1.0 - levenshtein_distance(s1, s2) / max_len

    if _HAS_JIEBA:
        k1 = set(jieba.cut(s1))
        k2 = set(jieba.cut(s2))
    else:
        k1 = set(s1)
        k2 = set(s2)
    union = k1 | k2
    if len(union) == 0:
        return lev_sim
    key_sim = len(k1 & k2) / len(union)

    return 0.4 * lev_sim + 0.6 * key_sim


def _clean_text(text: str) -> str:
    """清理文本：去标点、空格"""
    return re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', text)


def _text_contains(text: str, fragment: str) -> bool:
    """检查 fragment 是否为 text 的子串（去除标点空格后）"""
    return fragment in _clean_text(text)


# ── 规则引擎 ─────────────────────────────────────────

class RuleEngine:
    """
    本地规则引擎：将学生 OCR 文本与标准译文逐句对比，检测错误。
    """

    def __init__(self, standard_sentences: List[dict] = None):
        self.standard_sentences = standard_sentences or _STANDARD_SENTENCES

    def split_student_text(self, text: str) -> List[str]:
        """
        将学生文本分句。按句号、换行符分割，过滤空句。
        同时过滤掉卷面信息（标题行、姓名行等非译文内容）。
        """
        # 清理卷面元信息
        # 去掉 ☰ 涂改标记（百度 OCR 返回的涂改符号）
        text = text.replace('☰', '')
        # 去掉卷面元信息关键词
        text = re.sub(r'(豆神教育|豆伴匠|Doushen|姓名|班级|日期|教师点评|师点评|分数|小石潭记)[:：]?\s*', '', text)
        # 去掉开头的 "数:" 或 "数：" 编号
        text = re.sub(r'^数[:：]', '', text)
        # 去掉开头非译文内容（在"从"之前的内容）
        text = re.sub(r'^[^从小伐全青潭日其坐以同从]*', '', text)

        parts = re.split(r'[。\n]', text)
        result = []
        for p in parts:
            p = p.strip()
            if len(p) < 5:
                continue
            if len(p) > 30 and '；' in p:
                sub_parts = p.split('；')
                for sp in sub_parts:
                    sp = sp.strip()
                    if sp and len(sp) >= 3:
                        result.append(sp)
            else:
                result.append(p)
        return result

    def match_sentences(self, student_sentences: List[str]) -> Tuple[List[Tuple[str, str, float]], List[str]]:
        """
        将学生译文逐句匹配到标准译文。
        改进算法：双向最佳匹配，避免顺序错位。
        
        1. 先计算所有 (标准句, 学生句) 的相似度矩阵
        2. 按相似度从高到低排序，依次匹配
        3. 每个学生句和每个标准句只能匹配一次
        """
        if not student_sentences:
            return [], []
        
        # 计算相似度矩阵
        sim_matrix = []
        for si, std in enumerate(self.standard_sentences):
            std_text = std["translation"]
            for ji, stu in enumerate(student_sentences):
                sim = sentence_similarity(std_text, stu)
                sim_matrix.append((sim, si, ji, stu, std_text))
        
        # 按相似度降序排序
        sim_matrix.sort(key=lambda x: x[0], reverse=True)
        
        matched_std = {}  # std_idx -> (stu_text, std_text, sim)
        matched_stu = set()  # 已匹配的学生句索引
        
        for sim, si, ji, stu, std_text in sim_matrix:
            if si in matched_std:
                continue
            if ji in matched_stu:
                continue
            if sim < 0.03:  # 最低相似度阈值
                break
            matched_std[si] = (stu, std_text, sim)
            matched_stu.add(ji)
        
        # 组装结果（按标准句顺序）
        matched = []
        for si in range(len(self.standard_sentences)):
            if si in matched_std:
                matched.append(matched_std[si])
            else:
                std_text = self.standard_sentences[si]["translation"]
                matched.append(("", std_text, 0.0))
        
        unmatched = [student_sentences[i] for i in range(len(student_sentences)) if i not in matched_stu]
        return matched, unmatched

    def detect_errors(self, student_text: str, standard_text: str, keywords: List[str]) -> List[ErrorItem]:
        """
        检测一句中的翻译错误。

        核心逻辑（改进版）：
        1. 先检查语义等价表：如果学生文本命中语义等价项，视为正确，不检测错误
        2. 对每个关键词，查找规则表中它的明确错误形式
        3. 只有学生文本中**出现了 errors 列表中的错误写法**才扣分
        4. 正确翻译（correct）出现在学生文本中不扣分
        5. 检测漏译：检查 correct 的核心含义是否完全缺失
        """
        errors = []
        student_clean = _clean_text(student_text)

        for kw in keywords:
            rule = _KEYWORD_RULES.get(kw)
            if not rule:
                continue

            # ── 0. 语义等价检查（新增）──
            equivalents = _SEMANTIC_EQUIVALENTS.get(kw, [])
            is_equivalent = False
            for eq_form in equivalents:
                eq_clean = _clean_text(eq_form)
                if eq_clean and eq_clean in student_clean:
                    is_equivalent = True
                    break
            if is_equivalent:
                # 学生写了语义等价的表达，视为正确，跳过错误检测
                continue

            # 1. 检查是否有明确的错误写法
            found_error_form = None
            for err_form in rule.get("errors", []):
                err_clean = _clean_text(err_form)
                if err_clean and err_clean in student_clean:
                    found_error_form = err_form
                    break

            if found_error_form:
                errors.append(ErrorItem(
                    error_type=rule["type"],
                    original_text=found_error_form,
                    correct_text=rule["correct"],
                    reason=f"'{kw}'应译为'{rule['correct']}'，学生写作'{found_error_form}'，属{'实词' if rule['type'] == ErrorType.CONTENT_ERROR else '虚词'}错误",
                    deduction_points=rule["deduction"],
                    bbox=None,
                ))
                continue  # 已找到错误，跳过漏译检测

            # 2. 漏译检测：检查 correct 的核心含义是否缺失
            #    宽松策略：取 correct 的关键片段，只要学生文本中有任一关键词匹配即可
            correct_clean = _clean_text(rule["correct"])

            # 把 correct 按字符拆分，检查学生文本中是否包含至少一半
            if len(correct_clean) <= 2:
                has_match = correct_clean in student_clean
            elif len(correct_clean) <= 4:
                # 检查 correct 的连续2字子串是否出现
                has_match = any(
                    correct_clean[i:i+2] in student_clean
                    for i in range(len(correct_clean) - 1)
                )
            else:
                # 取首2字和末2字，任一匹配即可
                core1 = correct_clean[:2]
                core2 = correct_clean[-2:]
                has_match = core1 in student_clean or core2 in student_clean

            if not has_match:
                # 漏译检测前再做一次语义等价检查（用correct文本）
                if not is_equivalent:  # 前面已经检查过
                    errors.append(ErrorItem(
                        error_type=ErrorType.OMISSION,
                        original_text=kw,
                        correct_text=rule["correct"],
                        reason=f"遗漏了关键词'{kw}'（应译为'{rule['correct']}'），属漏译",
                        deduction_points=2,
                        bbox=None,
                    ))

        # 去重
        seen = {}
        for e in errors:
            key = e.original_text
            if key not in seen or e.deduction_points > seen[key].deduction_points:
                seen[key] = e
        return list(seen.values())

    def grade(self, student_full_text: str) -> List[SentenceAnalysis]:
        """
        主入口：对 OCR 识别出的学生全文进行批改。
        """
        student_sentences = self.split_student_text(student_full_text)
        matched, unmatched = self.match_sentences(student_sentences)

        analyses = []
        for i, std_sent in enumerate(self.standard_sentences):
            if i < len(matched):
                stu_text, std_text, sim = matched[i]
            else:
                stu_text, std_text, sim = "", std_sent["translation"], 0.0

            # 只有当学生有对应的翻译文本时才检测错误
            # sim < 0.05 表示几乎没有匹配，跳过（不标记为漏译）
            if not stu_text or sim < 0.05:
                analyses.append(SentenceAnalysis(
                    original_classical=std_sent["classical"],
                    student_translation=stu_text if stu_text else "（未识别到此句翻译）",
                    standard_translation=std_text,
                    errors=[],
                    sentence_score=100,  # 无法批改的句不扣分
                    is_excellent=False,
                    bbox=None,
                ))
                continue

            errors = self.detect_errors(stu_text, std_text, std_sent["keywords"])

            deductions = sum(e.deduction_points for e in errors)
            sent_score = max(0, 100 - deductions * 2)

            is_excellent = (len(errors) == 0 and sim > 0.4 and len(stu_text) > 10)

            analyses.append(SentenceAnalysis(
                original_classical=std_sent["classical"],
                student_translation=stu_text,
                standard_translation=std_text,
                errors=errors,
                sentence_score=sent_score,
                is_excellent=is_excellent,
                is_highlight=False,
                highlight_comment="",
                bbox=None,
            ))

        # 未匹配的句作为多译
        for extra in unmatched:
            if len(extra) < 5:
                continue
            analyses.append(SentenceAnalysis(
                original_classical="（多译内容）",
                student_translation=extra,
                standard_translation="",
                errors=[ErrorItem(
                    error_type=ErrorType.ADDITION,
                    original_text=extra[:30],
                    correct_text="",
                    reason="此句内容在原文中不存在对应内容，属多译",
                    deduction_points=1,
                    bbox=None,
                )],
                sentence_score=0,
                is_excellent=False,
                is_highlight=False,
                highlight_comment="",
            ))

        # 点睛句识别
        analyses = self._detect_highlights(analyses)

        return analyses

    def _detect_highlights(self, analyses: List[SentenceAnalysis]) -> List[SentenceAnalysis]:
        """基于规则识别点睛句，按《小石潭记批改要求》的8句必标库"""
        highlight_map = {
            "心乐之": "情感起点，'乐'字奠定全篇感情基调",
            "全石以为底": "石底奇观，铺排句式展现景物多样",
            "青树翠蔓": "景物描写典范，十二字写尽树木姿态",
            "空游无所依": "千古名句，侧面写水清",
            "日光下澈": "动静结合写游鱼，画面感强",
            "斗折蛇行": "比喻连用写溪流蜿蜒",
            "凄神寒骨": "情感由'乐'转'忧'的核心句",
            "以其境过清": "收束全篇，点明离去原因",
        }

        for sa in analyses:
            if "未识别" in sa.student_translation or not sa.student_translation:
                continue
            for keyword, comment in highlight_map.items():
                if keyword in sa.original_classical:
                    sa.is_highlight = True
                    sa.highlight_comment = comment
                    break

        return analyses
