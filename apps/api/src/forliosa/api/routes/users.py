"""Auth (dev login, logout) and the current user's profile/preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api.deps import create_session, current_user, destroy_session, signed_in_user
from forliosa.api.errors import ApiError
from forliosa.api.schemas import AccountDeleteIn, DevLoginIn, MePatch, PreferencesPatch, TermsAcceptIn, User
from forliosa.api.schemas_discussions import PublicNameIn
from forliosa.config import get_settings
from forliosa.db import get_db
from forliosa.ids import new_id
from forliosa.marketdata.service import get_market_data
from forliosa.models import User as UserModel
from forliosa.services import account, discussions
from forliosa.services.ledger_io import DEFAULT_PREFERENCES, preferences_of
from forliosa.timeutil import now_utc

router = APIRouter(tags=["auth"])


def user_out(db: Session, user: UserModel) -> dict:
    """The signed-in user's own profile, with their public name, whether they are a site admin and until when their
    public posting is suspended (``services.discussions``). Only ever returned to the user themselves."""
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "avatar_url": user.avatar_url,
            "preferences": preferences_of(user), **discussions.me_fields(db, user), **account.terms_fields(user)}


@router.post("/auth/dev-login", response_model=User, summary="開發用登入（僅 FORLIOSA_ENV=dev）")
def dev_login(body: DevLoginIn, response: Response, db: Session = Depends(get_db)):
    if not get_settings().is_dev:
        raise ApiError(404, "not_found", "找不到資源")
    email = body.email.strip().lower()
    user = db.scalar(select(UserModel).where(UserModel.email == email))
    if user is None:
        user = UserModel(id=new_id("usr"), email=email, display_name=body.display_name or email.split("@")[0],
                         preferences=dict(DEFAULT_PREFERENCES))
        account.record_terms_at_signup(user)
        db.add(user)
        db.commit()
    elif body.display_name and body.display_name != user.display_name:
        user.display_name = body.display_name
        db.commit()
    create_session(db, user, response)
    return user_out(db, user)


@router.post("/auth/logout", status_code=204, summary="登出")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    destroy_session(db, request, response)
    response.status_code = 204
    return response


@router.get("/me", response_model=User, tags=["me"])
@router.get("/users/me", response_model=User, tags=["me"], summary="同 GET /me")
def me(user: UserModel = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.patch("/me", response_model=User, tags=["me"], summary="修改顯示名稱（群組裡顯示的就是這個名稱）")
def patch_me(body: MePatch, user: UserModel = Depends(signed_in_user), db: Session = Depends(get_db)):
    user.display_name = body.display_name
    db.commit()
    return user_out(db, user)


@router.put("/users/me/public-name", response_model=User, tags=["me"],
            summary="設定或更改公開暱稱（公開討論用；不分大小寫與全半形唯一；7 天內只能改一次）")
@router.put("/me/public-name", response_model=User, include_in_schema=False)
def put_public_name(body: PublicNameIn, user: UserModel = Depends(signed_in_user), db: Session = Depends(get_db)):
    discussions.set_public_name(db, user, body.public_name)
    return user_out(db, user)


@router.patch("/me/preferences", response_model=User, tags=["me"])
def patch_preferences(body: PreferencesPatch, user: UserModel = Depends(current_user),
                      db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "benchmark" in changes:
        sym = get_market_data().resolve_benchmark(changes["benchmark"])
        if sym is None:
            raise ApiError(422, "unknown_symbol", f"找不到基準商品：{changes['benchmark']}")
        changes["benchmark"] = sym
    user = db.merge(user)
    user.preferences = {**preferences_of(user), **changes}
    db.commit()
    return user_out(db, user)


@router.get("/me/export", tags=["me"], summary="匯出我的資料（JSON 檔；只有這個帳號自己的資料）")
def export_me(user: UserModel = Depends(signed_in_user), db: Session = Depends(get_db)):
    """Always the signed-in person's own data (``X-Forliosa-View-As`` is ignored). At most 5 an hour."""
    account.check_export_rate(user.id)
    data = account.export_user(db, user)
    filename = f"forliosa-export-{now_utc():%Y%m%d}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                       "Cache-Control": "no-store"})


@router.delete("/me", status_code=204, tags=["me"], summary="刪除帳號（不能復原）")
def delete_me(body: AccountDeleteIn, request: Request, response: Response,
              user: UserModel = Depends(signed_in_user), db: Session = Depends(get_db)):
    if body.confirm != account.DELETE_CONFIRMATION:
        raise ApiError(422, "validation_error", f"請輸入「{account.DELETE_CONFIRMATION}」確認")
    account.delete_user(db, user)
    destroy_session(db, request, response)  # the session rows are gone with the account; this clears the cookie
    response.status_code = 204
    return response


@router.post("/me/terms-accept", response_model=User, tags=["me"], summary="確認已讀目前版本的服務條款與隱私權政策")
def accept_terms(body: TermsAcceptIn, user: UserModel = Depends(signed_in_user), db: Session = Depends(get_db)):
    account.accept_terms(db, user, body.version)
    return user_out(db, user)
