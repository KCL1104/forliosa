"""匯入對帳單 (``POST /imports/statement``, 產品負責人 2026-11-16) and 匯入庫存 (``POST /imports/positions``,
``POST /imports/positions/commit``, 2026-11-17): request and response bodies."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forliosa.ai.importer import TEXT_MAX_CHARS
from forliosa.api.schemas import BATCH_MAX_ROWS, BatchFlag, BatchProblem

ImageType = Literal["image/jpeg", "image/png", "image/webp"]


class ImportPageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: ImageType
    data: str = Field(min_length=8, description="base64（不含 data: 前綴）；檔頭要真的是 JPEG／PNG／WebP")
    text: str | None = Field(default=None, max_length=TEXT_MAX_CHARS,
                             description="PDF 塗過個資的文字層（最多 20,000 字）；截圖沒有")


class StatementImportIn(BaseModel):
    """Read as JSON from at most ``IMPORT_MAX_BODY_MB`` (15 MB) of body; at most ``IMPORT_MAX_PAGES`` (20) pages."""

    model_config = ConfigDict(extra="forbid")

    account_id: str | None = Field(default=None, max_length=40,
                                   description="用哪個帳戶檢查賣超與重複；不給就用第一個帳戶")
    kind: Literal["pdf", "images"]
    pages: list[ImportPageIn] = Field(min_length=1)


class ImportFlagOut(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"]


class ImportCandidateOut(BaseModel):
    """``TransactionIn`` without ``source`` (the batch write sets ``import``). ``note`` is always empty: what was read
    never goes into a note (the chat AI reads notes)."""

    account_id: str
    symbol: str | None = Field(description="找不到股票或對到好幾檔時是 null")
    type: str
    trade_date: str = Field(description="YYYY-MM-DD；日期沒讀到是空字串")
    quantity: float | int | None
    price: float | None
    amount: float | None = Field(description="對帳單印的價金（沒印是 null）；寫入時伺服器照股數 × 價格算")
    fee: float | None
    tax: float | None
    currency: str
    is_day_trade: bool
    note: str = ""


class ImportRowOut(BaseModel):
    row_id: str
    candidate: ImportCandidateOut
    raw: dict[str, Any] = Field(description="AI 照抄的字串（沒讀到是空字串）、頁碼與 raw_line")
    flags: list[ImportFlagOut]
    include: bool = Field(description="預設要不要匯入")


class TotalsCheckOut(BaseModel):
    ok: bool | None = Field(description="讀出來的列加起來和對帳單印的合計相符；沒印合計時是 null")
    diff: float | None = Field(description="讀出來的 − 印的（負的：可能漏讀）；相符或沒印時是 0／null")


class ProblemOut(BaseModel):
    code: str
    message: str


class StatementImportOut(BaseModel):
    document_kind: Literal["monthly_statement", "trade_confirmation", "app_screenshot", "holdings_snapshot",
                           "not_a_trade_record"]
    broker_name: str
    period: dict[str, str | None] | None = Field(description="{from, to}（YYYY-MM-DD）；沒印期間時是 null")
    rows: list[ImportRowOut]
    printed_totals: dict[str, str] | None = Field(description="對帳單印的合計（照抄的字串）；沒印時是 null")
    totals_check: TotalsCheckOut | None
    unreadable: list[str]
    embedded_instructions: list[str] = Field(description="檔案裡像指令的文字：照抄、沒有照做")
    model_used: str
    retried: bool = Field(description="有沒有用重讀的模型（AI_MODEL_IMPORT_RETRY）再讀一次")
    notice: str | None = Field(default=None, description="整份不能匯入時的一句話（庫存畫面、不是買賣紀錄）")
    problems: list[ProblemOut] = Field(default_factory=list, description="怪不到哪一列的帳目問題（帳本本來就對不上）")


# -- 匯入庫存 (2026-11-17) --------------------------------------------------------------------------------------------
class PositionsImportIn(BaseModel):
    """Read as JSON from at most ``IMPORT_MAX_BODY_MB`` of body. ``kind: "images"``: 1–``IMPORT_MAX_PAGES`` screenshots
    in ``pages`` (no ``text``); ``kind: "text"``: the pasted ``text`` (no ``pages``)."""

    model_config = ConfigDict(extra="forbid")

    account_id: str | None = Field(default=None, max_length=40,
                                   description="對哪個帳戶的帳本（已在帳本、其他帳戶也有）；不給就用第一個帳戶")
    kind: Literal["images", "text"]
    pages: list[ImportPageIn] = Field(default_factory=list, description="kind=images：庫存畫面的截圖")
    text: str | None = Field(default=None, max_length=TEXT_MAX_CHARS,
                             description="kind=text：貼上的庫存文字（最多 20,000 字；伺服器送出前再塗一次個資）")


class LedgerHoldingOut(BaseModel):
    """What the account holds now (the ledger's average includes buy fees)."""

    quantity: float | int
    avg_cost: float = Field(description="帳本的均價（原幣，含買進手續費）")
    currency: str
    records: int = Field(description="這個帳戶裡這一檔的紀錄筆數（以券商為準時會刪掉的）")
    dividends: int = Field(description="其中的股利（現金、股票股利，自動記的也算）：刪掉之後領過的股利不再算進損益")
    sells: int = Field(description="其中的賣出：刪掉之後賣出的已實現損益不再算進損益")


class PositionRowOut(BaseModel):
    row_id: str
    symbol: str | None = Field(description="找不到股票或對到好幾檔時是 null")
    name: str
    currency: str
    quantity: float | int | None = Field(description="股數（印的是張時已經乘 1,000）；沒讀到是 null")
    price: float | None = Field(description="每股成本：券商的均價，沒有均價時是總成本 ÷ 股數；沒讀到是 null")
    price_basis: Literal["average_cost", "total_cost"] | None = Field(
        description="price 從哪裡來；total_cost 時寫入請送 total_cost，帳本的總成本才會和券商一樣")
    total_cost: float | None = Field(description="畫面印的總成本；沒印是 null")
    raw: dict[str, Any] = Field(description="AI 照抄的字串（沒讀到是空字串）、頁碼與 raw_line")
    flags: list[ImportFlagOut]
    include: bool = Field(description="預設要不要匯入")
    in_ledger: LedgerHoldingOut | None = Field(description="這個帳戶現在已經有這一檔時，帳本裡的股數與均價")


class PositionsImportOut(BaseModel):
    account_id: str
    document_kind: Literal["holdings", "trade_records", "other"]
    broker_name: str
    trade_date: date = Field(description="預設的買進日期（今天，台北）")
    rows: list[PositionRowOut]
    merged_duplicates: int = Field(description="截圖重疊、完全一樣的列只算一次：合併了幾列")
    unreadable: list[str]
    embedded_instructions: list[str] = Field(description="圖片或文字裡像指令的字：照抄、沒有照做")
    model_used: str
    retried: bool
    notice: str | None = Field(default=None, description="一列都沒有時的一句話（交易明細、不是庫存）")


class PositionsCommitRowIn(BaseModel):
    """One position: ``price`` (the broker's average) or ``total_cost`` (price = total ÷ shares), exactly one."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    total_cost: Decimal | None = Field(default=None, gt=0)
    trade_date: date | None = Field(default=None, description="這一列自己的買進日期；不給就用整批的 trade_date")
    currency: Literal["TWD", "USD"] | None = None
    replace: bool = Field(default=False, description="以券商為準：先刪掉這個帳戶裡這一檔的所有紀錄")

    @model_validator(mode="after")
    def _one_cost(self) -> PositionsCommitRowIn:
        if (self.price is None) == (self.total_cost is None):
            raise ValueError("price or total_cost, exactly one")
        return self


class PositionsCommitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=40, description="寫進哪個帳戶（必填，不退回第一個帳戶）")
    trade_date: date | None = Field(default=None, description="整批的買進日期；不給是今天（台北）")
    dry_run: bool = False
    rows: list[PositionsCommitRowIn] = Field(min_length=1, max_length=BATCH_MAX_ROWS)


class ReplacedOut(BaseModel):
    symbol: str
    deleted: int = Field(description="以券商為準刪掉（dry_run：會刪掉）的舊紀錄筆數；整批復原不會還原它們")


class PositionsCommitRowCheck(BaseModel):
    index: int
    flags: list[BatchFlag]
    in_ledger: LedgerHoldingOut | None


class PositionsCommitCheck(BaseModel):
    """``dry_run: true``: nothing written or deleted. ``ok``: the same rows would be written now."""

    dry_run: Literal[True] = True
    ok: bool
    trade_date: date
    rows: list[PositionsCommitRowCheck]
    replaced: list[ReplacedOut]
    problems: list[BatchProblem]


class PositionsCommitCreated(BaseModel):
    dry_run: Literal[False] = False
    batch_id: str = Field(description="整批復原：DELETE /transactions/batches/{batch_id}")
    trade_date: date
    created: list[str] = Field(description="寫入的買進（transaction id），照送來的順序")
    replaced: list[ReplacedOut]
    auto_dividends_added: int


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema with nested models inlined (no ``$defs``), for ``openapi_extra``."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(o: Any) -> Any:
        if isinstance(o, dict):
            ref = o.get("$ref")
            if isinstance(ref, str):
                return walk(defs[ref.rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return walk(schema)
