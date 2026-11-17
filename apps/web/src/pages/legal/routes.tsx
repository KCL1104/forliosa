import { LegalPage } from "./LegalPage"

/** `/terms` */
export function TermsPage() {
  return <LegalPage doc="terms" />
}

/** `/privacy` */
export function PrivacyPage() {
  return <LegalPage doc="privacy" />
}

/** `/disclaimer`：免責聲明（全站頁尾的「免責聲明」連到這裡） */
export function DisclaimerPage() {
  return <LegalPage doc="disclaimer" />
}
