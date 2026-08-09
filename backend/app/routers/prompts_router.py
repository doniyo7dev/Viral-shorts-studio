"""
/api/prompts — Prompt Personalization: har bir foydalanuvchi o'zining bir nechta
shablonini saqlaydi, faollashtiradi, tahrirlaydi.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..database import get_cursor
from ..auth import get_current_user

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("")
def list_prompts(user: dict = Depends(get_current_user)):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM prompt_templates WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
        return cur.fetchall()


@router.get("/{prompt_id}")
def get_prompt(prompt_id: int, user: dict = Depends(get_current_user)):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM prompt_templates WHERE id = ? AND user_id = ?", (prompt_id, user["id"]))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Shablon topilmadi")
    return row


class PromptPayload(BaseModel):
    name: str
    audience: str = ""
    language: str = "uz"
    tone: str = "energetic"
    seo_focus: str = ""
    cta_text: str = ""
    use_emoji: bool = True
    keywords: str = ""
    banned_words: str = ""
    title_max_length: int = 100
    description_template: str = ""
    custom_instructions: str = ""


@router.post("")
def create_prompt(payload: PromptPayload, user: dict = Depends(get_current_user)):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO prompt_templates
               (user_id, name, is_active, audience, language, tone, seo_focus, cta_text, use_emoji,
                keywords, banned_words, title_max_length, description_template, custom_instructions)
               VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user["id"], payload.name, payload.audience, payload.language, payload.tone,
                payload.seo_focus, payload.cta_text, 1 if payload.use_emoji else 0,
                payload.keywords, payload.banned_words, payload.title_max_length,
                payload.description_template, payload.custom_instructions,
            ),
        )
        return {"success": True, "id": cur.lastrowid}


@router.patch("/{prompt_id}")
def update_prompt(prompt_id: int, payload: PromptPayload, user: dict = Depends(get_current_user)):
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM prompt_templates WHERE id = ? AND user_id = ?", (prompt_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Shablon topilmadi")

        cur.execute(
            """UPDATE prompt_templates SET
               name=?, audience=?, language=?, tone=?, seo_focus=?, cta_text=?, use_emoji=?,
               keywords=?, banned_words=?, title_max_length=?, description_template=?, custom_instructions=?
               WHERE id=? AND user_id=?""",
            (
                payload.name, payload.audience, payload.language, payload.tone,
                payload.seo_focus, payload.cta_text, 1 if payload.use_emoji else 0,
                payload.keywords, payload.banned_words, payload.title_max_length,
                payload.description_template, payload.custom_instructions, prompt_id, user["id"],
            ),
        )
    return {"success": True}


@router.post("/{prompt_id}/activate")
def activate_prompt(prompt_id: int, user: dict = Depends(get_current_user)):
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM prompt_templates WHERE id = ? AND user_id = ?", (prompt_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Shablon topilmadi")
        cur.execute("UPDATE prompt_templates SET is_active = 0 WHERE user_id = ?", (user["id"],))
        cur.execute(
            "UPDATE prompt_templates SET is_active = 1 WHERE id = ? AND user_id = ?", (prompt_id, user["id"])
        )
    return {"success": True}


@router.delete("/{prompt_id}")
def delete_prompt(prompt_id: int, user: dict = Depends(get_current_user)):
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM prompt_templates WHERE user_id = ?", (user["id"],))
        if cur.fetchone()["cnt"] <= 1:
            raise HTTPException(400, "Kamida bitta shablon qolishi kerak")
        cur.execute("DELETE FROM prompt_templates WHERE id = ? AND user_id = ?", (prompt_id, user["id"]))
    return {"success": True}
