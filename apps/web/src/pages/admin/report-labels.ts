/** 管理後台「市場報告」的字：模型的短名稱（揭曉後才顯示） */
const MODEL_TEXT: Record<string, string> = { "claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5" }

/** 「Opus 5.5・high」 */
export const writerText = (w: { model: string; effort: string }) => `${MODEL_TEXT[w.model] ?? w.model}・${w.effort}`
