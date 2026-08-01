"""Template registry — the ONLY place patient-facing strings live.

Each of the 11 templates (build doc §5.2) carries a Hindi + English body and,
where relevant, quick-reply buttons whose ids follow the CLAUDE.md conventions
(arrived:<entry_id>, cancel:<entry_id>, gapyes:<entry_id>, rebook:tomorrow).

Bodies use named `{placeholders}` filled from a ctx dict. `params` lists the
ordered names used to build Meta template components when sending out of the
24-hour window. Category is UTILITY for all.
"""

from __future__ import annotations

import dataclasses as dc


@dc.dataclass(frozen=True, slots=True)
class Button:
    """An outgoing quick-reply button (resolved id + localized title)."""

    id: str
    title: str


@dc.dataclass(frozen=True, slots=True)
class _Btn:
    """A template's button spec: id may contain a {placeholder}."""

    id: str
    hi: str
    en: str


@dc.dataclass(frozen=True, slots=True)
class Template:
    name: str
    hi: str
    en: str
    params: tuple[str, ...] = ()
    buttons: tuple[_Btn, ...] = ()
    category: str = "UTILITY"

    def text(self, lang: str, ctx: dict) -> str:
        body = self.hi if lang == "hi" else self.en
        return body.format(**{k: ctx.get(k, "") for k in _placeholders(body)})

    def render_buttons(self, lang: str, ctx: dict) -> list[Button]:
        out: list[Button] = []
        for b in self.buttons:
            bid = b.id.format(**{k: ctx.get(k, "") for k in _placeholders(b.id)})
            out.append(Button(id=bid, title=b.hi if lang == "hi" else b.en))
        return out

    def component_params(self, ctx: dict) -> list[str]:
        return [str(ctx.get(name, "")) for name in self.params]


def _placeholders(s: str) -> set[str]:
    import string

    return {f[1] for f in string.Formatter().parse(s) if f[1]}


_ARRIVED = _Btn("arrived:{entry_id}", "📍 मैं आ गया/गई", "📍 I've arrived")
_CANCEL = _Btn("cancel:{entry_id}", "❌ कैंसिल", "❌ Cancel")
_REBOOK = _Btn("rebook:tomorrow", "📅 कल बुक करें", "📅 Book tomorrow")
_GAPYES = _Btn("gapyes:{entry_id}", "✅ हाँ, पहले आऊँगा", "✅ Yes, I'll come earlier")


REGISTRY: dict[str, Template] = {
    t.name: t
    for t in (
        Template(
            "booking_confirmed",
            hi="नमस्ते {name} जी! अपॉइंटमेंट पक्का ✅ टोकन नं. {token} • डॉक्टर आपको लगभग {eta} बजे "
            "देखेंगे • कृपया {report} बजे तक क्लिनिक पहुँचें।",
            en="Hello {name}! Appointment confirmed ✅ Token no. {token} • Doctor will see you "
            "around {eta} • Please reach the clinic by {report}.",
            params=("name", "token", "eta", "report"),
            buttons=(_ARRIVED, _CANCEL),
        ),
        Template(
            "pre_arrival",
            hi="रिमाइंडर: आपका टोकन {token} • अनुमानित समय {eta} • कृपया {report} तक पहुँचें।",
            en="Reminder: your token {token} • estimated time {eta} • please reach by {report}.",
            params=("token", "eta", "report"),
            buttons=(_ARRIVED,),
        ),
        Template(
            "three_away",
            hi="आपसे पहले सिर्फ़ 3 मरीज़ हैं। अनुमानित समय {eta}। अगर क्लिनिक नहीं पहुँचे हैं तो अभी निकलें 🙏",
            en="Only 3 patients before you. Estimated time {eta}. If you haven't reached the "
            "clinic, please leave now 🙏",
            params=("eta",),
            buttons=(_ARRIVED,),
        ),
        Template(
            "you_are_next",
            hi="अब आपकी बारी है! कृपया रिसेप्शन पर आ जाएँ। टोकन {token}",
            en="It's your turn! Please come to reception. Token {token}",
            params=("token",),
        ),
        Template(
            "skipped_grace",
            hi="आपकी बारी आई पर आप क्लिनिक पर नहीं थे। {minutes} मिनट तक आपकी जगह रोकी गई है — "
            "पहुँचते ही बटन दबाएँ, आपको अगला नंबर मिलेगा।",
            en="Your turn came but you weren't at the clinic. Your place is held for {minutes} "
            "min — tap the button when you arrive and you'll be seen next.",
            params=("minutes",),
            buttons=(_ARRIVED,),
        ),
        Template(
            "eta_shift",
            hi="अपडेट: आपका नया अनुमानित समय {eta} है (टोकन {token})।",
            en="Update: your new estimated time is {eta} (token {token}).",
            params=("eta", "token"),
        ),
        Template(
            "delay_broadcast",
            hi="सूचना: डॉक्टर आज {minutes} मिनट देरी से आएँगे। आपका नया समय: {eta}। असुविधा के लिए खेद 🙏",
            en="Notice: the doctor is running {minutes} min late today. Your new time: {eta}. "
            "Sorry for the inconvenience 🙏",
            params=("minutes", "eta"),
        ),
        Template(
            "closed_broadcast",
            hi="क्षमा करें, आज क्लिनिक बंद है ({date})। कल के लिए बुक करें?",
            en="Sorry, the clinic is closed today ({date}). Book for tomorrow?",
            params=("date",),
            buttons=(_REBOOK,),
        ),
        Template(
            "gap_offer",
            hi="एक जगह खाली हुई! डॉक्टर आपको ~{new} बजे देख सकते हैं (पहले {old} था)। 5 मिनट में जवाब दें।",
            en="A slot opened up! The doctor can see you around {new} (was {old}). Reply within "
            "5 minutes.",
            params=("new", "old"),
            buttons=(_GAPYES,),
        ),
        Template(
            "expired_rebook",
            hi="आज आपकी अपॉइंटमेंट पूरी नहीं हो सकी। कल के लिए बुक करें?",
            en="Your appointment couldn't be completed today. Book for tomorrow?",
            buttons=(_REBOOK,),
        ),
        Template(
            "doctor_digest",
            hi="आज: {seen} मरीज़ देखे • {noshow} नो-शो • औसत {avg} मिनट • {wa} WhatsApp बुकिंग • "
            "कल सुबह {tomorrow} बुक हो चुके",
            en="Today: {seen} patients seen • {noshow} no-shows • avg {avg} min • {wa} WhatsApp "
            "bookings • {tomorrow} booked for tomorrow morning",
            params=("seen", "noshow", "avg", "wa", "tomorrow"),
        ),
    )
}


def get(name: str) -> Template:
    return REGISTRY[name]


# --------------------------------------------------------------------------- #
# Conversational UI strings (in-window free-form) — kept here so NO patient
# copy is hardcoded elsewhere. hi + en; formatted with named {placeholders}.
# --------------------------------------------------------------------------- #
PROMPTS: dict[str, dict[str, str]] = {
    "consent": {
        "hi": "ℹ️ बुकिंग के लिए हम आपका नाम व नंबर सुरक्षित रखते हैं। हटाने के लिए STOP लिखें।",
        "en": "ℹ️ We save your name & number for booking. Reply STOP to delete anytime.",
    },
    "choose_session": {"hi": "कौन सा सत्र?", "en": "Which session?"},
    "slots_left": {"hi": "{free} जगह बाकी", "en": "{free} slots left"},
    "slots_left_on": {
        "hi": "{date} • {free} जगह बाकी",
        "en": "{date} • {free} slots left",
    },
    "no_sessions": {
        "hi": "क्षमा करें, अभी कोई सत्र उपलब्ध नहीं है।",
        "en": "Sorry, no sessions are open for booking right now.",
    },
    "choose_time": {
        "hi": "कब आना चाहेंगे? 'जल्दी से जल्दी' दबाएँ या अपना समय लिखें (जैसे 7 baje)।",
        "en": "When would you like to come? Tap 'ASAP' or type your time (e.g. 7 pm).",
    },
    "choose_profile": {"hi": "किसके लिए?", "en": "For whom?"},
    "ask_name": {"hi": "मरीज़ का नाम लिखें।", "en": "Please type the patient's name."},
    "medical_safe": {
        "hi": "कृपया इस बारे में डॉक्टर से मिलने पर बात करें। 🙏",
        "en": "Please discuss this with the doctor at your visit. 🙏",
    },
    "cancel_confirm": {
        "hi": "क्या आप अपनी बुकिंग रद्द करना चाहते हैं?",
        "en": "Do you want to cancel your booking?",
    },
    "cancelled": {
        "hi": "आपकी बुकिंग रद्द कर दी गई है।",
        "en": "Your booking has been cancelled.",
    },
    "no_active": {
        "hi": "आपकी कोई सक्रिय बुकिंग नहीं है।",
        "en": "You have no active booking.",
    },
    "arrived_ack": {
        "hi": "धन्यवाद! आपकी उपस्थिति दर्ज हो गई है।",
        "en": "Thank you! We've marked you as arrived.",
    },
    "status_line": {
        "hi": "टोकन {token} • आपसे पहले {ahead} मरीज़ • अनुमानित समय {eta}",
        "en": "Token {token} • {ahead} ahead of you • estimated time {eta}",
    },
    "stop_done": {
        "hi": "आपका डेटा हटा दिया गया है और सक्रिय बुकिंग रद्द कर दी गई है। 🙏",
        "en": "Your data has been deleted and any active booking cancelled. 🙏",
    },
    "overflow": {
        "hi": "यह सत्र भरा है। कृपया दूसरा सत्र चुनें:",
        "en": "This session is full. Please pick another:",
    },
    "low_confidence": {
        "hi": "माफ़ करें, समझ नहीं आया। नीचे बटन से चुनें या 'menu' लिखें।",
        "en": "Sorry, I didn't catch that. Use a button below or type 'menu' to restart.",
    },
    "greeting_has_active": {
        "hi": (
            "आपका टोकन {token} • आपसे पहले {ahead} मरीज़ • अनुमानित समय {eta} 📋"
            " रद्द करने के लिए 'cancel' लिखें।"
        ),
        "en": (
            "Your token {token} • {ahead} ahead of you • est. time {eta} 📋"
            " Type 'cancel' to cancel your booking."
        ),
    },
    "gap_accepted": {
        "hi": "बढ़िया! आपका समय पहले कर दिया गया है।",
        "en": "Great! You've been moved earlier.",
    },
    # --- booking transparency (never move a patient silently) ------------- #
    # Sent when the typed time lands outside the chosen session's window and
    # BOTH the AM and PM readings miss it. We re-ask instead of clamping: a
    # patient who is told the time doesn't fit can choose again; a patient
    # who is silently moved 5 hours believes the clinic's system is broken.
    "time_out_of_window": {
        "hi": "यह समय इस सत्र में नहीं है ({start}–{end})। कोई और समय बताएं या "
        "'जल्दी से जल्दी' दबाएँ।",
        "en": "That time isn't in this session ({start}–{end}). Please type another time "
        "or tap 'ASAP'.",
    },
    # Sent just before booking_confirmed when the granted time had to move more
    # than 10 minutes from what the patient asked for.
    "adjusted_to_start": {
        "hi": "आपने {requested} कहा था, पर सत्र {start} से शुरू होता है — आपको शुरुआत का "
        "नंबर दिया गया है।",
        "en": "You asked for {requested}, but this session starts at {start} — you've been "
        "given a token from the start of the session.",
    },
    "adjusted_to_now": {
        "hi": "आपने {requested} कहा था, पर वह समय निकल चुका है — आपको अभी की कतार में "
        "नंबर दिया गया है।",
        "en": "You asked for {requested}, but that time has already passed — you've been "
        "given a token in the current queue.",
    },
    # Sent when the booking is NOT for today. Without this a patient booking at
    # 11 PM reads the ETA and comes to the clinic tonight.
    "booking_day_tomorrow": {
        "hi": "ध्यान दें: यह बुकिंग *कल* ({date}) के {session} सत्र की है — आज की नहीं।",
        "en": "Please note: this booking is for *TOMORROW* ({date}), the {session} session "
        "— not today.",
    },
    "booking_day_other": {
        "hi": "ध्यान दें: यह बुकिंग *{date}* के {session} सत्र की है — आज की नहीं।",
        "en": "Please note: this booking is for *{date}*, the {session} session — not today.",
    },
}

# Interactive button labels for conversational prompts (id, hi, en).
BTN_ASAP = _Btn("time:asap", "जल्दी से जल्दी", "ASAP")
BTN_SELF = _Btn("profile:self", "खुद", "Myself")
BTN_FAMILY = _Btn("profile:family", "परिवार", "Family")
BTN_CANCEL_YES = _Btn("confirmcancel:yes", "हाँ, रद्द करें", "Yes, cancel")
BTN_CANCEL_NO = _Btn("confirmcancel:no", "नहीं", "No")


#: Session names as stored in `sessions.name`. Unknown names (a clinic may use
#: its own) fall through unchanged rather than being dropped.
SESSION_LABELS: dict[str, dict[str, str]] = {
    "morning": {"hi": "सुबह", "en": "morning"},
    "afternoon": {"hi": "दोपहर", "en": "afternoon"},
    "evening": {"hi": "शाम", "en": "evening"},
    "night": {"hi": "रात", "en": "night"},
}


def session_label(name: str, lang: str) -> str:
    """Patient-facing name of a session ('evening' -> 'शाम')."""
    pair = SESSION_LABELS.get((name or "").strip().lower())
    return pair["hi" if lang == "hi" else "en"] if pair else name


def prompt(key: str, lang: str, **fmt: object) -> str:
    body = PROMPTS[key]["hi" if lang == "hi" else "en"]
    return body.format(**fmt) if fmt else body


def btn(spec: _Btn, lang: str) -> Button:
    return Button(id=spec.id, title=spec.hi if lang == "hi" else spec.en)
