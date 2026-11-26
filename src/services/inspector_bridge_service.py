"""Ponte Inspector → ClickUp: lê a lista da sala, pede ao Claude as tarefas comprovadas e grava.

Ver as regras em inspector_bridge.py. Três garantias que não dependem do modelo:
- só grava em listas cujo space (segundo o próprio ClickUp) é o space de laboratório configurado;
- o % de uma tarefa nunca desce (plan_updates);
- a tarefa escolhida tem de existir entre as tarefas-folha da lista (enum no esquema + validação).
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Awaitable, Callable

from src.core.config import settings
from src.core.logging import logger
from src.services import inspector_bridge as rules
from src.services.schedule_fields import FIELD_COMPLETION, FIELD_PERCENT, date_to_ms, find_field
from src.services.schedule_service import status_names

# (system, conteúdo do utilizador, esquema) → texto JSON da resposta
ModelCall = Callable[[str, list[dict], dict], Awaitable[str]]


class BridgeError(Exception):
    """Registo que não pode ser aplicado (sala sem lista, space errado, resposta inválida)."""


def room_lists() -> dict[str, str]:
    if settings.inspector_bridge_room_lists.strip():
        try:
            data = json.loads(settings.inspector_bridge_room_lists)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except ValueError:
            logger.warning("INSPECTOR_BRIDGE_ROOM_LISTS não é JSON válido; a usar o mapa padrão")
    return dict(rules.DEFAULT_ROOM_LISTS)


async def call_claude(system: str, content: list[dict], schema: dict) -> str:
    """Uma chamada ao Claude com saída JSON validada pelo esquema."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
    response = await client.beta.messages.create(
        model=settings.inspector_bridge_model,
        max_tokens=16000,
        # Recusa por engano do classificador de segurança: a API repete o pedido noutro modelo.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise BridgeError("o modelo recusou o pedido")
    if response.stop_reason == "max_tokens":
        raise BridgeError("resposta do modelo cortada (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise BridgeError("resposta do modelo sem texto")
    return text


def _photos(payload: dict) -> list[dict]:
    photos = []
    for i, photo in enumerate(payload.get("photos") or [], 1):
        try:
            data = base64.b64decode(photo.get("data") or "", validate=True)
        except (ValueError, TypeError):
            continue
        if data:
            photos.append({"filename": photo.get("filename") or f"foto_{i}.jpg", "data": data,
                           "mime": photo.get("mime") or "image/jpeg", "b64": photo["data"],
                           "comment": photo.get("comment") or ""})
    return photos


def _record_day(payload: dict) -> date:
    try:
        return datetime.fromisoformat(str(payload.get("recorded_at"))[:19]).date()
    except ValueError:
        return date.today()


class InspectorBridgeService:
    def __init__(self, clickup, model_call: ModelCall | None = None, *, space_id: str | None = None,
                 managed_lists: list[str] | None = None, notify_list: Callable[[str], None] | None = None) -> None:
        self._clickup = clickup
        self._model_call = model_call or call_claude
        self._space_id = space_id if space_id is not None else settings.inspector_bridge_space_id
        self._managed = set(managed_lists if managed_lists is not None
                            else (settings.schedule_lists if settings.schedule_enabled else []))
        self._notify = notify_list

    async def resolve_list(self, city: str, room: str) -> dict:
        if not self._space_id:
            raise BridgeError("INSPECTOR_BRIDGE_SPACE_ID não configurado: nada é gravado")
        list_name = rules.room_list_name(room, room_lists())
        if not list_name:
            raise BridgeError(f'sala "{room}" sem lista correspondente no ClickUp')
        folder = rules.match_folder(await self._clickup.get_folders(self._space_id), city)
        if not folder:
            raise BridgeError(f'cidade "{city}" sem pasta no space de laboratório')
        match = next((lst for lst in folder.get("lists") or [] if rules.norm(lst.get("name")) == rules.norm(list_name)), None)
        if not match:
            raise BridgeError(f'pasta "{folder.get("name")}" sem a lista "{list_name}"')
        info = await self._clickup.get_list(match["id"])
        # A pasta veio deste space, mas a decisão de gravar fica com o que o ClickUp diz da lista.
        if str((info.get("space") or {}).get("id")) != str(self._space_id):
            raise BridgeError(f'lista {match["id"]} não pertence ao space de laboratório')
        return info

    async def process(self, payload: dict, dry_run: bool = False) -> dict:
        info = await self.resolve_list(payload.get("city", ""), payload.get("room", ""))
        list_id = info["id"]
        tasks = await self._clickup.get_tasks(list_id)
        fields = await self._clickup.get_list_fields(list_id)
        f_percent = find_field(fields, FIELD_PERCENT, "manual_progress")
        if not f_percent:
            raise BridgeError(f'lista {list_id} sem o campo "{FIELD_PERCENT}"')
        f_completion = find_field(fields, FIELD_COMPLETION, "date")
        candidates = rules.leaf_candidates(tasks)
        if not candidates:
            raise BridgeError(f"lista {list_id} sem tarefas")

        photos = _photos(payload)
        content: list[dict] = []
        for i, photo in enumerate(photos[:rules.MAX_PHOTOS_TO_MODEL], 1):
            content.append({"type": "text", "text": f"FOTO {i}" + (f" — comentário: {photo['comment']}" if photo["comment"] else "")})
            content.append({"type": "image", "source": {"type": "base64", "media_type": photo["mime"], "data": photo["b64"]}})
        list_name = info.get("name") or ""
        mapping = room_lists()
        content.append({"type": "text", "text": rules.build_user_text(
            payload, candidates, min(len(photos), rules.MAX_PHOTOS_TO_MODEL), list_name,
            rules.rooms_of_list(list_name, mapping), mapping)})
        raw = await self._model_call(rules.SYSTEM_PROMPT, content, rules.response_schema(candidates))
        try:
            plan = rules.plan_updates(raw, candidates)
        except (ValueError, TypeError) as exc:
            raise BridgeError(f"resposta do modelo inválida: {exc}") from exc

        result = {"list_id": list_id, "list_name": info.get("name"), "dry_run": dry_run, "note": plan.note,
                  "applied": [], "skipped": plan.skipped, "errors": []}
        if dry_run:
            result["applied"] = [vars(u) for u in plan.updates]
            return result

        names = status_names((info.get("statuses") or []))
        managed = list_id in self._managed
        by_id = {t["id"]: t for t in tasks}
        for update in plan.updates:
            try:
                await self._apply(update, payload, photos, by_id.get(update.task_id, {}), f_percent, f_completion,
                                  names, managed)
                result["applied"].append(vars(update))
            except Exception as exc:  # noqa: BLE001 — uma tarefa com erro não impede as outras
                logger.warning(f"Ponte Inspector: falha ao gravar a tarefa {update.task_id}: {exc}")
                result["errors"].append(f"{update.path}: {exc}")
        if managed and result["applied"] and self._notify:
            self._notify(list_id)
        return result

    async def _apply(self, update: rules.Update, payload: dict, photos: list[dict], task: dict, f_percent: dict,
                     f_completion: dict | None, names, managed: bool) -> None:
        attached = photos[:rules.MAX_PHOTOS_PER_TASK]
        await self._clickup.create_comment(update.task_id, rules.comment_text(update, payload, len(attached)),
                                           notify_all=False)
        for photo in attached:
            await self._clickup.upload_attachment(update.task_id, photo["filename"], photo["data"], photo["mime"])
        await self._clickup.set_custom_field(update.task_id, f_percent["id"], {"current": update.after})
        if update.after == 100 and f_completion:
            # Concluída no dia da inspeção, não no dia em que a ponte correu.
            await self._clickup.set_custom_field(update.task_id, f_completion["id"], date_to_ms(_record_day(payload)))
        if not managed:
            # Sem o motor do cronograma nesta lista, o status acompanha o % aqui mesmo.
            target = names.done if update.after >= 100 else names.in_progress
            if rules.norm((task.get("status") or {}).get("status")) != rules.norm(target):
                await self._clickup.set_task_status(update.task_id, target)
