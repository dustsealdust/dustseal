"""从《环世界》本地存档读取殖民者，再调用大模型生成背景故事。

说明（新手必读）：
- 游戏本身不会执行 Python。把本文件拖进 Mods 目录，游戏也不会自动运行它。
- 正确用法：用 Python 手动运行本脚本。脚本会去游戏的 Saves 目录读 .rws 存档。
- .rws 本质是 XML（偶尔是 gzip），里面有名字、年龄、技能。这是最简单的离线读法。
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from openai import OpenAI

# 环世界：1 年 = 3_600_000 tick
TICKS_PER_YEAR = 3_600_000

SKILL_ZH = {
    "Shooting": "射击",
    "Melee": "近战",
    "Construction": "建造",
    "Mining": "采矿",
    "Cooking": "烹饪",
    "Plants": "种植",
    "Animals": "驯兽",
    "Crafting": "手工",
    "Artistic": "艺术",
    "Medicine": "医疗",
    "Social": "社交",
    "Intellectual": "智识",
}

# API 配置：优先读环境变量，也可用 base_url 指向兼容服务
API_KEY = os.getenv("OPENAI_API_KEY", "sk-your-key-here")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ---------------------------------------------------------------------------
# 小工具：从 XML 节点安全取文本（节点不存在时返回默认值）
# ---------------------------------------------------------------------------
def xml_text(node: ET.Element | None, path: str, default: str = "") -> str:
    if node is None:
        return default
    child = node.find(path)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def default_saves_dir() -> Path:
    """Windows 默认存档目录（游戏 Options 里也能看到）。"""
    return (
        Path.home()
        / "AppData"
        / "LocalLow"
        / "Ludeon Studios"
        / "RimWorld by Ludeon Studios"
        / "Saves"
    )


def find_save_file(explicit: str | None = None) -> Path:
    """按优先级找一份 .rws：命令行路径 > 脚本同目录 > 默认 Saves 里最新一份。"""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            sys.exit(f"找不到存档: {path}")
        return path

    here = Path(__file__).resolve().parent
    local_saves = sorted(here.glob("*.rws"), key=lambda p: p.stat().st_mtime, reverse=True)
    if local_saves:
        return local_saves[0]

    saves_dir = default_saves_dir()
    if not saves_dir.is_dir():
        sys.exit(
            "没有找到存档目录。请用 --save 指定 .rws 路径，"
            f"或把存档复制到脚本旁边。\n默认目录应为: {saves_dir}"
        )

    rws = sorted(saves_dir.glob("*.rws"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not rws:
        sys.exit(f"存档目录是空的: {saves_dir}")
    return rws[0]


def load_save_root(path: Path) -> ET.Element:
    """解析 .rws：先当普通 XML，失败再当 gzip。"""
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return ET.parse(f).getroot()


def player_faction_ids(root: ET.Element) -> set[str]:
    """玩家殖民地在存档里类似 Faction_8，要先从 factionManager 对上 loadID。"""
    ids: set[str] = set()
    for fac in root.findall(".//factionManager/allFactions/li"):
        defn = xml_text(fac, "def")
        if defn in {"PlayerColony", "PlayerTribe"}:
            load_id = xml_text(fac, "loadID")
            if load_id:
                ids.add(f"Faction_{load_id}")
    return ids


def pawn_display_name(pawn: ET.Element) -> str:
    first = xml_text(pawn, "name/first")
    nick = xml_text(pawn, "name/nick")
    last = xml_text(pawn, "name/last")
    if nick and nick not in {first, last}:
        return f"{first} '{nick}' {last}".strip()
    return f"{first} {last}".strip()


def pawn_age_years(pawn: ET.Element) -> int:
    ticks = xml_text(pawn, "ageTracker/ageBiologicalTicks", "0")
    try:
        return int(ticks) // TICKS_PER_YEAR
    except ValueError:
        return 0


def pawn_skills(pawn: ET.Element) -> dict[str, int]:
    skills: dict[str, int] = {}
    for li in pawn.findall("skills/skills/li"):
        defn = xml_text(li, "def")
        if not defn:
            continue
        level_text = xml_text(li, "level", "0")
        try:
            level = int(level_text)
        except ValueError:
            level = 0
        skills[SKILL_ZH.get(defn, defn)] = level
    return skills


def is_dead(pawn: ET.Element) -> bool:
    return xml_text(pawn, "healthTracker/dead").lower() == "true"


def parse_colonists(root: ET.Element) -> list[dict]:
    """从存档里抽出玩家阵营、还活着、带技能的人形殖民者。"""
    factions = player_faction_ids(root)
    colonists: list[dict] = []
    seen_ids: set[str] = set()

    # 地图上的人 + 世界地图（商队）上的人，都会以 Pawn 节点出现
    for pawn in root.iter("thing"):
        if pawn.get("Class") not in {None, "Pawn"}:
            continue
        if pawn.find("name") is None or pawn.find("skills") is None:
            continue
        if is_dead(pawn):
            continue
        if factions and xml_text(pawn, "faction") not in factions:
            continue

        thing_id = xml_text(pawn, "id") or pawn_display_name(pawn)
        if thing_id in seen_ids:
            continue
        seen_ids.add(thing_id)

        name = pawn_display_name(pawn)
        if not name:
            continue

        colonists.append(
            {
                "id": thing_id,
                "name": name,
                "age": pawn_age_years(pawn),
                "kind": xml_text(pawn, "kindDef", "Colonist"),
                "skills": pawn_skills(pawn),
            }
        )

    return colonists


def pick_colonist(colonists: list[dict], name_query: str | None) -> dict:
    if not colonists:
        sys.exit("这份存档里没有解析到玩家殖民者。确认游戏已保存，且角色还活着。")

    if name_query:
        q = name_query.lower()
        for c in colonists:
            if q in c["name"].lower():
                return c
        sys.exit(f"没有名字包含 {name_query!r} 的殖民者。当前名单：{[c['name'] for c in colonists]}")

    return colonists[0]


def build_prompt(character: dict) -> str:
    """把角色字典拼成环世界世界观 Prompt。"""
    skills_text = "、".join(
        f"{skill} {level} 级" for skill, level in character["skills"].items()
    )
    return (
        "你是《环世界》(RimWorld) 的叙事作者。请根据下列殖民者数据，"
        "用中文写一段 200～400 字的角色背景故事。\n"
        "要求：贴合环世界设定（坠毁、部落、帝国、机械族、精神创伤、"
        "技能与经历挂钩）；语气偏冷硬、略带黑色幽默；不要列表，写成连贯短文。\n\n"
        f"姓名：{character['name']}\n"
        f"年龄：{character['age']}\n"
        f"类型：{character.get('kind', 'Colonist')}\n"
        f"技能：{skills_text}\n"
    )


def generate_backstory(character: dict) -> str:
    """调用 OpenAI 兼容 API，返回生成的背景故事文本。"""
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    prompt = build_prompt(character)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "你只输出角色背景故事正文，不要加标题或解释。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.85,
        max_tokens=800,
    )
    return (response.choices[0].message.content or "").strip()


def save_character_json(
    character: dict,
    backstory: str,
    output_path: str | Path = "character_backstory.json",
) -> Path:
    """把角色数据与故事合并后保存为 JSON。"""
    path = Path(output_path)
    payload = {
        **character,
        "backstory": backstory,
        "setting": "RimWorld",
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="从 RimWorld 存档读取殖民者并生成背景故事")
    parser.add_argument("--save", help="指定 .rws 存档路径；不填则自动找最新存档")
    parser.add_argument("--name", help="按名字（或昵称片段）选一个殖民者；不填则用名单第一个")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析存档、不调用大模型（先确认数据对不对）",
    )
    args = parser.parse_args()

    save_path = find_save_file(args.save)
    print(f"使用存档: {save_path}")

    root = load_save_root(save_path)
    colonists = parse_colonists(root)

    print("=== 存档中的殖民者 ===")
    for i, c in enumerate(colonists, start=1):
        print(f"  {i}. {c['name']}  年龄 {c['age']}  技能 {c['skills']}")

    character = pick_colonist(colonists, args.name)
    print("\n=== 选中的角色 ===")
    print(json.dumps(character, ensure_ascii=False, indent=2))

    if args.dry_run:
        out = save_character_json(character, backstory="")
        print(f"\n已跳过 API。空故事 JSON 写到: {out.resolve()}")
        return

    print("\n正在调用大模型生成环世界背景故事...\n")
    story = generate_backstory(character)

    print("=== 生成的背景故事 ===")
    print(story)

    out = save_character_json(character, story)
    print(f"\n已保存到: {out.resolve()}")


if __name__ == "__main__":
    main()
