"""Auth (dev login, logout) and the current user's profile/preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api.deps import create_session, current_user, destroy_session
from forliosa.api.errors import ApiError
from forliosa.api.schemas import DevLoginIn, PreferencesPatch, User
from forliosa.config import get_settings
from forliosa.db import get_db
from forliosa.ids import new_id
from forliosa.marketdata.service import get_market_data
from forliosa.models import User as UserModel
from forliosa.services.ledger_io import DEFAULT_PREFERENCES, preferences_of

router = APIRouter(tags=["auth"])


def user_out(user: UserModel) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "preferences": preferences_of(user)}


@router.post("/auth/dev-login", response_model=User, summary="開發用登入（僅 FORLIOSA_ENV=dev）")
def dev_login(body: DevLoginIn, response: Response, db: Session = Depends(get_db)):
    if not get_settings().is_dev:
        raise ApiError(404, "not_found", "找不到資源")
    email = body.email.strip().lower()
    user = db.scalar(select(UserModel).where(UserModel.email == email))
    if user is None:
        user = UserModel(id=new_id("usr"), email=email, display_name=body.display_name or email.split("@")[0],
                         preferences=dict(DEFAULT_PREFERENCES))
        db.add(user)
        db.commit()
    elif body.display_name and body.display_name != user.display_name:
        user.display_name = body.display_name
        db.commit()
    create_session(db, user, response)
    return user_out(user)


@router.post("/auth/logout", status_code=204, summary="登出")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    destroy_session(db, request, response)
    response.status_code = 204
    return response


@router.get("/me", response_model=User, tags=["me"])
def me(user: UserModel = Depends(current_user)):
    return user_out(user)


@router.patch("/me/preferences", response_model=User, tags=["me"])
def patch_preferences(body: PreferencesPatch, user: UserModel = Depends(current_user),
                      db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "benchmark" in changes:
        sym = get_market_data().resolve(changes["benchmark"])
        if sym is None:
            raise ApiError(422, "unknown_symbol", f"找不到基準商品：{changes['benchmark']}")
        changes["benchmark"] = sym
    user = db.merge(user)
    user.preferences = {**preferences_of(user), **changes}
    db.commit()
    return user_out(user)
