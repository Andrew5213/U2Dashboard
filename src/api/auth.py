from fastapi import APIRouter, Depends, Query, Response

from src.core.logging import logger
from src.core.nextcloud_auth import NextcloudUser, is_enabled, nextcloud_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def who_am_i(
    response: Response,
    # só o caminho, sem nada que permita forjar linhas no log
    page: str = Query(default="", max_length=200, pattern=r"^[\w/\-.]*$",
                      description="página que o utilizador abriu (só para o log)"),
    user: NextcloudUser | None = Depends(nextcloud_user),
):
    """Quem está a ver, segundo o token do Nextcloud enviado pela página
    (`X-Nextcloud-JWT`). É identificação, não login: sem token válido a resposta é
    `authenticated: false` e a app continua a funcionar como sempre."""
    response.headers["Cache-Control"] = "no-store"
    if user is None:
        return {"enabled": is_enabled(), "authenticated": False, "user": None}
    logger.info(f"Nextcloud: {user.uid} ({user.display_name or user.email or 'sem nome'}) abriu {page or '/'}")
    return {"enabled": True, "authenticated": True, "user": user.as_dict()}
