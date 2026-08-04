/**
 * The panel's ONLY string dictionary.
 *
 * Mirrors the `wa/templates.py` rule: patient-facing copy lives in exactly one
 * file, every entry carries both `hi` and `en`. This file extends that rule to
 * the staff-facing panel.
 *
 * Why the panel ships its own translations instead of letting the browser do
 * it: Chrome's auto-translate rendered `हो गए` (served) as "Have become" and
 * `बंद` (closed, a state) as "Close" (an imperative) — sitting right next to
 * the control that closes a session. A machine translator rewriting
 * destructive-action labels is unacceptable in a clinic, so the page is marked
 * `translate="no"` and everything below is authored by hand.
 *
 * Typing: `satisfies Record<string, Pair>` makes a missing `hi` or `en` a
 * compile error. No `any`.
 */

export type Lang = "hi" | "en";

export interface Pair {
  hi: string;
  en: string;
}

export const strings = {
  // --- identity / auth ---------------------------------------------------- //
  appName: { hi: "क्लिनिकक्यू", en: "ClinicQ" },
  login: { hi: "लॉगिन", en: "Login" },
  slug: { hi: "क्लिनिक कोड", en: "Clinic code" },
  pin: { hi: "6 अंकों का PIN", en: "6-digit PIN" },
  enter: { hi: "अंदर जाएँ", en: "Enter" },

  wrongPin: { hi: "गलत कोड या PIN", en: "Wrong code or PIN" },

  // --- day / session ------------------------------------------------------ //
  today: { hi: "आज", en: "Today" },
  tomorrow: { hi: "कल", en: "Tomorrow" },
  viewOnly: {
    hi: "यह आगे का सत्र है — सिर्फ़ देख सकते हैं",
    en: "Future session — view only",
  },
  noSessionThatDay: { hi: "उस दिन कोई सत्र नहीं", en: "No session that day" },
  noSessionToday: { hi: "आज कोई सत्र नहीं", en: "No session today" },
  sessionTimePassed: {
    hi: "यह सत्र का समय बीत चुका है — कल का सत्र अपने आप खुलेगा",
    en: "This session's time has passed — tomorrow's opens automatically",
  },
  sessionClosedNote: { hi: "सत्र बंद है", en: "Session closed" },
  sessionCancelledNote: { hi: "सत्र रद्द है", en: "Session cancelled" },

  // session names (from `sessions.name`)
  sessionMorning: { hi: "सुबह", en: "Morning" },
  sessionEvening: { hi: "शाम", en: "Evening" },

  // session status chips — `sesClosed` is a STATE, never an instruction
  sesOpen: { hi: "चालू", en: "Open" },
  sesPaused: { hi: "रुका", en: "Paused" },
  sesScheduled: { hi: "बाकी", en: "Scheduled" },
  sesClosed: { hi: "बंद", en: "Closed" },
  sesCancelled: { hi: "रद्द", en: "Cancelled" },

  // --- live queue --------------------------------------------------------- //
  nowServing: { hi: "अभी अंदर", en: "Now serving" },
  noneServing: { hi: "कोई अंदर नहीं", en: "Nobody in consult" },
  consult: { hi: "परामर्श", en: "consult" },
  next: { hi: "अगला बुलाएँ", en: "Call next" },
  nextUp: { hi: "अगला", en: "Next up" },
  waiting: { hi: "इंतज़ार में", en: "Waiting" },
  served: { hi: "हो गए", en: "Served" },
  avg: { hi: "औसत", en: "Avg" },
  token: { hi: "टोकन", en: "Token" },
  target: { hi: "समय", en: "Target" },
  eta: { hi: "अनुमान", en: "ETA" },
  emptyQueue: { hi: "कतार खाली है", en: "Queue is empty" },
  emptyHint: {
    hi: "वॉक-इन जोड़ें या मरीज़ के आने का इंतज़ार करें",
    en: "Add a walk-in or wait for patients",
  },

  // relative-time units, used by `lib/format.ts`
  relNow: { hi: "अभी", en: "now" },
  relMin: { hi: "मिनट", en: "min" },
  relHourShort: { hi: "घ", en: "h" },
  relMinShort: { hi: "मि", en: "m" },

  // --- walk-in ------------------------------------------------------------ //
  walkin: { hi: "वॉक-इन", en: "Walk-in" },
  addWalkin: { hi: "वॉक-इन जोड़ें", en: "Add walk-in" },
  name: { hi: "मरीज़ का नाम", en: "Patient name" },
  phone: { hi: "फ़ोन (वैकल्पिक)", en: "Phone (optional)" },
  add: { hi: "जोड़ें", en: "Add" },
  cancel: { hi: "रद्द करें", en: "Cancel" },
  close: { hi: "बंद करें", en: "Close" },

  // --- row actions -------------------------------------------------------- //
  markArrived: { hi: "आ गए", en: "Mark arrived" },
  cancelToken: { hi: "टोकन रद्द", en: "Cancel token" },
  callNow: { hi: "अभी बुलाएँ", en: "Call now" },

  // --- session controls --------------------------------------------------- //
  controls: { hi: "सत्र नियंत्रण", en: "Session controls" },
  /** Top-bar button label. Short enough not to truncate at 360px in English. */
  controlsShort: { hi: "नियंत्रण", en: "Controls" },
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

  // --- overflow menu ------------------------------------------------------ //
  more: { hi: "और", en: "More" },
  language: { hi: "भाषा", en: "Language" },
  langHi: { hi: "हिन्दी", en: "हिन्दी" },
  langEn: { hi: "English", en: "English" },
  settings: { hi: "सेटिंग", en: "Settings" },

  // --- toasts / banners --------------------------------------------------- //
  undo: { hi: "वापस लें", en: "Undo" },
  offline: { hi: "फिर जुड़ रहे हैं…", en: "Reconnecting…" },
  sessionFull: { hi: "सत्र भर गया", en: "Session full" },
  invalidTransition: { hi: "अभी यह नहीं हो सकता", en: "Not possible right now" },
  genericError: { hi: "कुछ गड़बड़ हुई", en: "Something went wrong" },
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

  // --- generic ------------------------------------------------------------ //
  yes: { hi: "हाँ", en: "Yes" },
  no: { hi: "नहीं", en: "No" },
  save: { hi: "सेव करें", en: "Save" },
  saved: { hi: "सेव हो गया", en: "Saved" },
  logout: { hi: "लॉगआउट", en: "Logout" },

  // --- entry status chips ------------------------------------------------- //
  stBooked: { hi: "बुक", en: "Booked" },
  stArrived: { hi: "आ गए", en: "Arrived" },
  stCalled: { hi: "बुलाया", en: "Called" },
  stInConsult: { hi: "अंदर", en: "In consult" },
  stGrace: { hi: "छूटे", en: "Grace" },
  stDone: { hi: "हो गया", en: "Done" },
  stCancelled: { hi: "रद्द", en: "Cancelled" },
  stExpired: { hi: "समाप्त", en: "Expired" },

  // --- settings page ------------------------------------------------------ //
  cardClinic: { hi: "क्लिनिक", en: "Clinic" },
  cardLangOptions: { hi: "भाषा और विकल्प", en: "Language & options" },
  cardTimetable: { hi: "साप्ताहिक समय", en: "Weekly timetable" },
  cardChangePin: { hi: "PIN बदलें", en: "Change PIN" },
  fieldName: { hi: "नाम", en: "Name" },
  fieldDoctor: { hi: "डॉक्टर", en: "Doctor" },
  fieldSpecialty: { hi: "विशेषज्ञता", en: "Specialty" },
  fieldFee: { hi: "फीस ₹", en: "Fee ₹" },
  clinicLanguage: { hi: "मरीज़ों की भाषा", en: "Patient language" },
  gapOffers: { hi: "गैप ऑफर", en: "Gap offers" },
  remove: { hi: "हटाएँ", en: "Remove" },
  startTime: { hi: "शुरू", en: "Start" },
  endTime: { hi: "अंत", en: "End" },
  tokenCap: { hi: "टोकन सीमा", en: "Token cap" },
  noTimetableRows: { hi: "कोई सत्र नहीं", en: "No sessions" },
  addTimetableRow: { hi: "सत्र जोड़ें", en: "Add row" },
  newPinPlaceholder: { hi: "नया 6-अंकों का PIN", en: "New 6-digit PIN" },
  loadFailed: { hi: "लोड नहीं हुआ", en: "Load failed" },
  saveFailed: { hi: "सेव नहीं हुआ", en: "Save failed" },
  pinSixDigits: { hi: "PIN 6 अंकों का हो", en: "PIN must be 6 digits" },

  // weekdays, Monday-first to match `timetable.weekday`
  wd0: { hi: "सोम", en: "Mon" },
  wd1: { hi: "मंगल", en: "Tue" },
  wd2: { hi: "बुध", en: "Wed" },
  wd3: { hi: "गुरु", en: "Thu" },
  wd4: { hi: "शुक्र", en: "Fri" },
  wd5: { hi: "शनि", en: "Sat" },
  wd6: { hi: "रवि", en: "Sun" },
} satisfies Record<string, Pair>;

export type StringKey = keyof typeof strings;

/**
 * Count-aware confirm copy for the session-control sheet. These cannot be flat
 * entries because they interpolate live queue counts; each returns a `Pair` so
 * a missing locale is still a compile error.
 */
export const templates = {
  closeInConsult: (token: number, name: string): Pair => ({
    hi: `टोकन #${token} (${name || "—"}) अभी अंदर हैं — बंद करने पर उनका परामर्श पूरा मान लिया जाएगा।`,
    en: `Token #${token} (${name || "—"}) is in consult — closing marks their consult as done.`,
  }),
  closeWaiting: (waiting: number): Pair => ({
    hi: `${waiting} मरीज़ इंतज़ार में हैं। बंद करने पर सभी को कल आने का संदेश भेजा जाएगा।`,
    en: `${waiting} waiting — all will be messaged to come tomorrow.`,
  }),
  closeGeneric: (): Pair => ({
    hi: "सत्र बंद किया जाएगा।",
    en: "The session will be closed.",
  }),
  cancelWaiting: (waiting: number): Pair => ({
    hi: `${waiting} मरीज़ों को "क्लिनिक आज बंद है" संदेश भेजा जाएगा।`,
    en: `"Clinic closed today" will be sent to ${waiting} patient(s).`,
  }),
  cancelGeneric: (): Pair => ({
    hi: "आज का सत्र रद्द किया जाएगा।",
    en: "Today's session will be cancelled.",
  }),
  cancelServedNudge: (served: number): Pair => ({
    hi: `${served} मरीज़ देखे जा चुके हैं — "आज रद्द करें" उस सत्र के लिए है जो हुआ ही नहीं। देखे जा चुके हों तो "आज बंद करें" सही है।`,
    en: `${served} already seen — "Cancel today" is for a session that never happened; "Close today" is usually right once patients are seen.`,
  }),
  reopenWarning: (): Pair => ({
    hi: "फिर से खोलने पर जिन मरीज़ों को पहले ही संदेश भेजा जा चुका है वे वापस नहीं आएँगे। केवल नया काम (वॉक-इन, नई बुकिंग, अगला) फिर चालू होगा।",
    en: "Reopening does NOT bring back patients who were already notified. It only re-enables work (walk-ins, new bookings, NEXT).",
  }),
};

/** Resolve a `Pair` in the given locale. */
export function pick(pair: Pair, lang: Lang): string {
  return lang === "hi" ? pair.hi : pair.en;
}
