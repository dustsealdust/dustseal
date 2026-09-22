"""用 OpenAI 兼容 API 为环世界风格角色生成背景故事。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# 角色基础数据（可按需改）
# ---------------------------------------------------------------------------
CHARACTER: dict = {
    "name": "Kara 'Ash' Venn",
    "age": 34,
    "skills": {
        "射击": 8,
        "医疗": 5,
        "建造": 3,
        "种植": 2,
        "社交": 6,
        "智识": 7,
    },
}

# API 配置：优先读环境变量，也可用 base_url 指向兼容服务
API_KEY = os.getenv("OPENAI_API_KEY", "sk-your-key-here")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


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
    print("=== 角色基础数据 ===")
    print(json.dumps(CHARACTER, ensure_ascii=False, indent=2))
    print("\n正在调用大模型生成环世界背景故事...\n")

    story = generate_backstory(CHARACTER)

    print("=== 生成的背景故事 ===")
    print(story)

    out = save_character_json(CHARACTER, story)
    print(f"\n已保存到: {out.resolve()}")


if __name__ == "__main__":
    main()
