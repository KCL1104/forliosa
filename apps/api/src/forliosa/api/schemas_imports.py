"""匯入對帳單 (``POST /imports/statement``): request and response bodies (產品負責人 2026-11-16)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from forliosa.ai.importer import TEXT_MAX_CHARS

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
