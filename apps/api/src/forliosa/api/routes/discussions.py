"""Discussion threads: topics, replies, reactions, reports, and the site admins' moderation of public content
(docs/api-contract.md 「討論串…」).

Public topics and their replies are readable without a session; everything else needs one. Every endpoint acts as the
signed-in user themselves (``signed_in_user`` / ``optional_user``), never as a delegation's owner. Group-scope
content is 404 for non-members; ``/admin/*`` is 404 for everyone who is not a site admin (``ADMIN_EMAILS``).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from forliosa.api.deps import optional_user, signed_in_user
from forliosa.api.schemas_discussions import (
    TARGET_PATTERN,
    AdminReportPage,
    ModerationIn,
    ReactionIn,
    Reply,
    ReplyIn,
    ReplyPage,
    ReportIn,
    SuspensionIn,
    SuspensionOut,
    Topic,
    TopicIn,
    TopicPage,
)
from forliosa.api.schemas_sharing import EmojiLiteral
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import discussions as svc

router = APIRouter(tags=["discussions"])
admin_router = APIRouter(prefix="/admin/discussions", tags=["discussions-admin"])


def site_admin(user: User = Depends(signed_in_user)) -> User:
    svc.require_admin(user)
    return user


# -- topics -----------------------------------------------------------------------------------------------------
@router.get("/discussions/topics", response_model=TopicPage, response_model_exclude_unset=True,
            summary="討論主題（公開的不用登入；group／all／mine 要登入；隱藏的不列出）")
def list_topics(scope: Literal["public", "group", "all"] = Query("public"),
                group_id: str | None = Query(None, max_length=32), symbol: str | None = Query(None, max_length=20),
                mine: bool = Query(False), sort: Literal["active", "new"] = Query("active"),
                limit: int = Query(30, ge=1, le=100), cursor: str | None = Query(None, max_length=300),
                user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    return svc.list_topics(db, get_market_data(), user, scope, group_id, symbol, mine, sort, limit, cursor)


@router.post("/discussions/topics", response_model=Topic, response_model_exclude_unset=True, status_code=201,
             summary="開主題（公開要先有公開暱稱；最多標記 5 檔商品）")
def create_topic(body: TopicIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.create_topic(db, get_market_data(), user, body.scope, body.group_id, body.title, body.body,
                            body.symbols or [])


@router.get("/discussions/topics/{topic_id}", response_model=Topic, response_model_exclude_unset=True,
            summary="一個主題（隱藏的：body 為 null，作者與站方管理員除外）")
def get_topic(topic_id: str, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    return svc.get_topic(db, get_market_data(), user, topic_id)


@router.delete("/discussions/topics/{topic_id}", status_code=204, response_class=Response,
               summary="刪除主題與它的回覆、表情、檢舉（作者；群組的擁有者與管理員）")
def delete_topic(topic_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    svc.delete_topic(db, user, topic_id)
    return Response(status_code=204)


# -- replies ----------------------------------------------------------------------------------------------------
@router.get("/discussions/topics/{topic_id}/replies", response_model=ReplyPage, response_model_exclude_unset=True,
            summary="回覆（舊到新）")
def list_replies(topic_id: str, limit: int = Query(50, ge=1, le=100),
                 cursor: str | None = Query(None, max_length=300), user: User | None = Depends(optional_user),
                 db: Session = Depends(get_db)):
    return svc.list_replies(db, user, topic_id, limit, cursor)


@router.post("/discussions/topics/{topic_id}/replies", response_model=Reply, response_model_exclude_unset=True,
             status_code=201, summary="回覆（隱藏的主題不能回覆：409 topic_hidden）")
def create_reply(topic_id: str, body: ReplyIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.create_reply(db, user, topic_id, body.body)


@router.delete("/discussions/replies/{reply_id}", status_code=204, response_class=Response,
               summary="刪除回覆（作者；群組的擁有者與管理員）")
def delete_reply(reply_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    svc.delete_reply(db, user, reply_id)
    return Response(status_code=204)


# -- reactions and reports --------------------------------------------------------------------------------------
@router.put("/discussions/reactions", status_code=204, response_class=Response, summary="加表情（重複呼叫不重複計）")
def put_reaction(body: ReactionIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    svc.put_reaction(db, user, body.target, body.emoji)
    return Response(status_code=204)


@router.delete("/discussions/reactions", status_code=204, response_class=Response, summary="收回自己的表情")
def delete_reaction(target: str = Query(min_length=3, max_length=48, pattern=TARGET_PATTERN),
                    emoji: EmojiLiteral = Query(...), user: User = Depends(signed_in_user),
                    db: Session = Depends(get_db)):
    svc.delete_reaction(db, user, target, emoji)
    return Response(status_code=204)


@router.post("/discussions/reports", status_code=204, response_class=Response,
             summary="檢舉公開內容（同一人對同一則只算一次；不能檢舉自己的或群組裡的）")
def report(body: ReportIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    svc.report(db, user, body.target, body.reason, body.note)
    return Response(status_code=204)


# -- site admin (public content only; not an admin → 404) -------------------------------------------------------
@admin_router.get("/reports", response_model=AdminReportPage, summary="檢舉，依對象彙整（不含 email、user_id）")
def admin_reports(status: Literal["open", "resolved"] = Query("open"), limit: int = Query(30, ge=1, le=100),
                  cursor: str | None = Query(None, max_length=300), _admin: User = Depends(site_admin),
                  db: Session = Depends(get_db)):
    return svc.admin_reports(db, status, limit, cursor)


@admin_router.post("/moderation", status_code=204, response_class=Response,
                   summary="hide：隱藏並結案；unhide：恢復顯示；dismiss：不隱藏、結案")
def moderate(body: ModerationIn, _admin: User = Depends(site_admin), db: Session = Depends(get_db)):
    svc.moderate(db, body.target, body.action)
    return Response(status_code=204)


@admin_router.get("/suspensions", response_model=list[SuspensionOut], summary="目前停權中的公開發言")
def list_suspensions(_admin: User = Depends(site_admin), db: Session = Depends(get_db)):
    return svc.list_suspensions(db)


@admin_router.post("/suspensions", response_model=SuspensionOut, status_code=201,
                   summary="暫停某一則公開內容的作者的公開發言（days：1、7、30 或 null＝永久）")
def create_suspension(body: SuspensionIn, admin: User = Depends(site_admin), db: Session = Depends(get_db)):
    return svc.create_suspension(db, admin, body.target, body.days, body.reason)


@admin_router.delete("/suspensions/{suspension_id}", status_code=204, response_class=Response, summary="解除停權")
def lift_suspension(suspension_id: str, _admin: User = Depends(site_admin), db: Session = Depends(get_db)):
    svc.lift_suspension(db, suspension_id)
    return Response(status_code=204)
