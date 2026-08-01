/**
 * Hindi-first labels with an English fallback. The panel audience reads Hindi;
 * English sits underneath in a smaller weight where space allows. `t()` returns
 * both so components decide the layout.
 */
export type Lang = "hi" | "en";

type Pair = { hi: string; en: string };

export const STRINGS = {
  appName: { hi: "क्लिनिकक्यू", en: "ClinicQ" },
  login: { hi: "लॉगिन", en: "Login" },
  slug: { hi: "क्लिनिक कोड", en: "Clinic code" },
  pin: { hi: "6 अंकों का PIN", en: "6-digit PIN" },
  enter: { hi: "अंदर जाएँ", en: "Enter" },
  wrongPin: { hi: "गलत कोड या PIN", en: "Wrong code or PIN" },

  today: { hi: "आज", en: "Today" },
  tomorrow: { hi: "कल", en: "Tomorrow" },
  viewOnly: {
    hi: "यह कल का सत्र है — सिर्फ़ देख सकते हैं",
    en: "Future session — view only",
  },
  noSessionThatDay: { hi: "उस दिन कोई सत्र नहीं", en: "No session that day" },
  sessionTimePassed: {
    hi: "यह सत्र का समय बीत चुका है — कल का सत्र अपने आप खुलेगा",
    en: "This session's time has passed — tomorrow's opens automatically",
  },

  nowServing: { hi: "अभी अंदर", en: "Now serving" },
  noneServing: { hi: "कोई अंदर नहीं", en: "Nobody in consult" },
  next: { hi: "अगला बुलाएँ", en: "Call next" },
  waiting: { hi: "इंतज़ार में", en: "Waiting" },
  served: { hi: "हो गए", en: "Served" },
  avg: { hi: "औसत", en: "Avg" },
  min: { hi: "मिनट", en: "min" },
  token: { hi: "टोकन", en: "Token" },
  target: { hi: "समय", en: "Target" },
  eta: { hi: "अनुमान", en: "ETA" },
  emptyQueue: { hi: "कतार खाली है", en: "Queue is empty" },
  emptyHint: {
    hi: "वॉक-इन जोड़ें या मरीज़ के आने का इंतज़ार करें",
    en: "Add a walk-in or wait for patients",
  },

  walkin: { hi: "वॉक-इन", en: "Walk-in" },
  addWalkin: { hi: "वॉक-इन जोड़ें", en: "Add walk-in" },
  name: { hi: "मरीज़ का नाम", en: "Patient name" },
  phone: { hi: "फ़ोन (वैकल्पिक)", en: "Phone (optional)" },
  add: { hi: "जोड़ें", en: "Add" },
  cancel: { hi: "रद्द करें", en: "Cancel" },
  close: { hi: "बंद करें", en: "Close" },

  markArrived: { hi: "आ गए", en: "Mark arrived" },
  cancelToken: { hi: "टोकन रद्द", en: "Cancel token" },
  callNow: { hi: "अभी बुलाएँ", en: "Call now" },

  controls: { hi: "सत्र नियंत्रण", en: "Session controls" },
  start: { hi: "सत्र शुरू", en: "Start session" },
  pause: { hi: "रोकें", en: "Pause" },
  resume: { hi: "फिर शुरू", en: "Resume" },
  late: { hi: "देरी", en: "Running late" },
  emergency: { hi: "इमरजेंसी", en: "Emergency" },
  closeToday: { hi: "आज बंद करें", en: "Close today" },
  cancelToday: { hi: "आज रद्द करें", en: "Cancel today" },
  reopen: { hi: "फिर से खोलें", en: "Reopen" },
  closeConfirmYes: { hi: "हाँ, बंद करें", en: "Yes, close" },
  cancelConfirmYes: { hi: "हाँ, आज रद्द करें", en: "Yes, cancel today" },
  reopenConfirmYes: { hi: "हाँ, फिर से खोलें", en: "Yes, reopen" },
  back: { hi: "वापस", en: "Back" },
  settings: { hi: "सेटिंग", en: "Settings" },

  undo: { hi: "वापस लें", en: "Undo" },
  undone: { hi: "वापस ले लिया", en: "Undone" },
  offline: { hi: "फिर जुड़ रहे हैं…", en: "Reconnecting…" },
  sessionFull: { hi: "सत्र भर गया", en: "Session full" },

  confirm: { hi: "पक्का?", en: "Sure?" },
  yes: { hi: "हाँ", en: "Yes" },
  no: { hi: "नहीं", en: "No" },
  save: { hi: "सेव करें", en: "Save" },
  saved: { hi: "सेव हो गया", en: "Saved" },
  logout: { hi: "लॉगआउट", en: "Logout" },

  staleData: { hi: "पुराना डेटा", en: "Offline — not live" },
  minutesAgo: { hi: "मिनट पहले", en: "min ago" },
  noConnection: { hi: "कनेक्शन नहीं", en: "Can't reach server" },
  noConnectionHint: {
    hi: "10 मिनट से ज़्यादा समय से सर्वर से संपर्क नहीं हो रहा।",
    en: "Server unreachable for over 10 minutes.",
  },
  reload: { hi: "रीफ़्रेश करें", en: "Reload" },
  reloadHint: {
    hi: "अगर डेटा गलत दिखे — ⋯ मेनू → रीफ़्रेश करें",
    en: "If data looks wrong — ⋯ menu → Reload",
  },

  status: {
    booked: { hi: "बुक", en: "Booked" },
    arrived: { hi: "आ गए", en: "Arrived" },
    called: { hi: "बुलाया", en: "Called" },
    in_consult: { hi: "अंदर", en: "In consult" },
    skipped: { hi: "छूटे", en: "Skipped" },
    grace: { hi: "छूटे", en: "Grace" },
    done: { hi: "हो गया", en: "Done" },
    cancelled: { hi: "रद्द", en: "Cancelled" },
    expired: { hi: "समाप्त", en: "Expired" },
  },
} satisfies Record<string, unknown>;

export function pick(pair: Pair, lang: Lang): string {
  return lang === "hi" ? pair.hi : pair.en;
}
