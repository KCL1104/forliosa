"""Family groups (親友群組): groups, members, invites, share settings, leaderboard, holdings, feed, comments and
reactions, weekly AI digests and push channels. Non-members get 404 everywhere; what members see of each other comes
from ``services.sharing``."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from forliosa.api.deps import session_user, signed_in_user
from forliosa.api.schemas_sharing import (
    TARGET_PATTERN,
    AcceptIn,
    ChannelPatch,
    Channels,
    CommentIn,
    CommentOut,
    CommentPage,
    DigestPage,
    DiscordIn,
    EmojiLiteral,
    FeedPage,
    GroupHoldings,
    GroupIn,
    GroupOut,
    GroupPatch,
    GroupSummary,
    InviteIn,
    InviteOut,
    InvitePreview,
    Leaderboard,
    ReactionIn,
    Reactions,
    RoleIn,
    SharedPortfolio,
    ShareSettings,
    TelegramLink,
    TransferIn,
)
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import channels, digests, sharing
from forliosa.services import groups as svc

router = APIRouter(tags=["groups"])


# -- groups -------------------------------------------------------------------------------------------------
@router.get("/groups", response_model=list[GroupSummary], summary="我加入的群組")
def list_groups(user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.my_groups(db, get_market_data(), user)


@router.post("/groups", response_model=GroupOut, status_code=201, summary="建立群組（建立者為擁有者）")
def create_group(body: GroupIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.group_out(db, svc.create_group(db, user, body.name), user)


@router.get("/groups/{group_id}", response_model=GroupOut)
def get_group(group_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, _ = svc.require_member(db, group_id, user)
    return svc.group_out(db, g, user)


@router.patch("/groups/{group_id}", response_model=GroupOut, summary="改名（管理員）、開關排行（擁有者）")
def patch_group(group_id: str, body: GroupPatch, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    svc.update_group(db, g, m, body.model_dump(exclude_unset=True, exclude_none=True))
    return svc.group_out(db, g, user)


@router.delete("/groups/{group_id}", status_code=204, response_class=Response, summary="刪除群組（擁有者）")
def delete_group(group_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    svc.delete_group(db, g, m)
    return Response(status_code=204)


@router.post("/groups/{group_id}/transfer", response_model=GroupOut,
             summary="把擁有者轉給另一位成員（原擁有者變管理員）")
def transfer(group_id: str, body: TransferIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    svc.transfer(db, g, m, body.user_id)
    return svc.group_out(db, g, user)


@router.patch("/groups/{group_id}/members/{user_id}", response_model=GroupOut, summary="變更成員角色（擁有者）")
def set_role(group_id: str, user_id: str, body: RoleIn, user: User = Depends(signed_in_user),
             db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    svc.set_role(db, g, m, user_id, body.role)
    return svc.group_out(db, g, user)


@router.delete("/groups/{group_id}/members/{user_id}", status_code=204, response_class=Response,
               summary="移除成員（管理員）或離開群組（自己）")
def remove_member(group_id: str, user_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    svc.remove_member(db, g, m, user_id)
    return Response(status_code=204)


# -- invites ------------------------------------------------------------------------------------------------
@router.post("/groups/{group_id}/invites", response_model=InviteOut, status_code=201,
             summary="建立邀請連結（url 只在建立時回傳）")
def create_invite(group_id: str, body: InviteIn | None = None, user: User = Depends(signed_in_user),
                  db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    body = body or InviteIn()
    return svc.create_invite(db, g, m, body.expires, body.multi_use)


@router.get("/groups/{group_id}/invites", response_model=list[InviteOut], response_model_exclude_unset=True,
            summary="有效的邀請（不含 url）")
def list_invites(group_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return svc.list_invites(db, g, m)


@router.delete("/groups/{group_id}/invites/{invite_id}", status_code=204, response_class=Response)
def revoke_invite(group_id: str, invite_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    svc.revoke_invite(db, g, m, invite_id)
    return Response(status_code=204)


@router.get("/invites/{token}", response_model=InvitePreview, response_model_exclude_unset=True,
            summary="邀請預覽（不需登入；已是成員時多 group_id）")
def preview_invite(token: str, request: Request, db: Session = Depends(get_db)):
    return svc.preview_invite(db, token, session_user(request, db))


@router.post("/invites/{token}/accept", response_model=GroupOut, summary="接受邀請（必須先選好分享設定）")
def accept_invite(token: str, body: AcceptIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g = svc.accept_invite(db, token, user, body.share.model_dump())
    return svc.group_out(db, g, user)


# -- my share settings ---------------------------------------------------------------------------------------
@router.get("/groups/{group_id}/share", response_model=ShareSettings, summary="我在這個群組的分享設定")
def get_share(group_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, _ = svc.require_member(db, group_id, user)
    return sharing.share_out(next(m.share for m in sharing.members_of(db, g.id) if m.user_id == user.id))


@router.put("/groups/{group_id}/share", response_model=ShareSettings, summary="更新我在這個群組的分享設定（立即生效）")
def put_share(group_id: str, body: ShareSettings, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return svc.put_share(db, g, m, body.model_dump())


# -- projections ----------------------------------------------------------------------------------------------
@router.get("/groups/{group_id}/leaderboard", response_model=Leaderboard,
            summary="排行：今日、本月、今年（只有開了報酬率的成員）")
def leaderboard(group_id: str, period: str = Query("day", max_length=8), user: User = Depends(signed_in_user),
                db: Session = Depends(get_db)):
    g, _ = svc.require_member(db, group_id, user)
    md = get_market_data()
    return sharing.leaderboard(sharing.Projector(db, md), g, sharing.members_of(db, g.id), user.id, period.lower())


@router.get("/groups/{group_id}/holdings", response_model=GroupHoldings, summary="持股重疊（只有開了持股的成員）")
def holdings(group_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, _ = svc.require_member(db, group_id, user)
    return sharing.group_holdings(sharing.Projector(db, get_market_data()), sharing.members_of(db, g.id))


@router.get("/groups/{group_id}/members/{user_id}/shared", response_model=SharedPortfolio,
            response_model_exclude_unset=True, summary="一位成員開放的內容（沒開放的區塊不出現）")
def member_shared(group_id: str, user_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, _ = svc.require_member(db, group_id, user)
    member = svc.member_or_404(sharing.members_of(db, g.id), user_id)
    return sharing.shared_portfolio(sharing.Projector(db, get_market_data()), member)


@router.get("/groups/{group_id}/feed", response_model=FeedPage, response_model_exclude_unset=True,
            summary="交易動態（最近 90 天，新到舊）")
def feed(group_id: str, limit: int = Query(30, ge=1, le=100), cursor: str | None = Query(None, max_length=300),
         user_id: str | None = Query(None, max_length=32), user: User = Depends(signed_in_user),
         db: Session = Depends(get_db)):
    g, _ = svc.require_member(db, group_id, user)
    return sharing.feed_page(db, get_market_data(), g, sharing.members_of(db, g.id), user.id, limit, cursor, user_id)


# -- comments and reactions ---------------------------------------------------------------------------------------
@router.get("/groups/{group_id}/comments", response_model=CommentPage, summary="一個對象的留言（舊到新）")
def list_comments(group_id: str, target: str = Query(min_length=3, max_length=64, pattern=TARGET_PATTERN),
                  limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None, max_length=300),
                  user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return svc.list_comments(db, get_market_data(), g, m, target, limit, cursor)


@router.post("/groups/{group_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(group_id: str, body: CommentIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return svc.add_comment(db, get_market_data(), g, m, body.target, body.body)


@router.delete("/groups/{group_id}/comments/{comment_id}", status_code=204, response_class=Response,
               summary="刪除留言（作者或管理員）")
def delete_comment(group_id: str, comment_id: str, user: User = Depends(signed_in_user),
                   db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    svc.delete_comment(db, get_market_data(), g, m, comment_id)
    return Response(status_code=204)


@router.put("/groups/{group_id}/reactions", response_model=Reactions, summary="加表情（重複呼叫不重複計）")
def put_reaction(group_id: str, body: ReactionIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return svc.put_reaction(db, get_market_data(), g, m, body.target, body.emoji)


@router.delete("/groups/{group_id}/reactions", response_model=Reactions, summary="收回自己的表情")
def delete_reaction(group_id: str, target: str = Query(min_length=3, max_length=64, pattern=TARGET_PATTERN),
                    emoji: EmojiLiteral = Query(...), user: User = Depends(signed_in_user),
                    db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return svc.delete_reaction(db, get_market_data(), g, m, target, emoji)


# -- weekly AI digests ---------------------------------------------------------------------------------------------
@router.get("/groups/{group_id}/digests", response_model=DigestPage,
            summary="群組 AI 週報（新到舊；facts 依目前的分享設定過濾）")
def list_digests(group_id: str, limit: int = Query(8, ge=1, le=52), cursor: str | None = Query(None, max_length=300),
                 user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, _ = svc.require_member(db, group_id, user)
    return digests.digests_page(db, g, user.id, limit, cursor)


# -- push channels ---------------------------------------------------------------------------------------------------
@router.get("/groups/{group_id}/channels", response_model=Channels,
            summary="推播頻道（每位成員都看得到；webhook_hint 只有擁有者看得到）")
def get_channels(group_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return channels.channels_out(db, g, m)


@router.put("/groups/{group_id}/channels/discord", response_model=Channels,
            summary="設定 Discord webhook（擁有者；先送測試訊息，失敗 422 webhook_failed）")
def put_discord(group_id: str, body: DiscordIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    channels.put_discord(db, g, m, body.webhook_url, body.notify_trades, body.notify_digest)
    return channels.channels_out(db, g, m)


@router.patch("/groups/{group_id}/channels/{kind}", response_model=Channels, summary="推播項目開關（擁有者）")
def patch_channel(group_id: str, kind: Literal["discord", "telegram"], body: ChannelPatch,
                  user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    channels.patch_channel(db, g, m, kind, body.model_dump(exclude_unset=True, exclude_none=True))
    return channels.channels_out(db, g, m)


@router.delete("/groups/{group_id}/channels/{kind}", status_code=204, response_class=Response,
               summary="解除推播頻道（擁有者）")
def delete_channel(group_id: str, kind: Literal["discord", "telegram"], user: User = Depends(signed_in_user),
                   db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    channels.delete_channel(db, g, m, kind)
    return Response(status_code=204)


@router.post("/groups/{group_id}/channels/telegram/link", response_model=TelegramLink,
             summary="Telegram 連結碼（擁有者；10 分鐘、一次性）")
def telegram_link(group_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    g, m = svc.require_member(db, group_id, user)
    return channels.create_link_code(db, g, m)
