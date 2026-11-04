"""Language helpers for the voice call: names, detection from text, explicit switch requests, and the switch policy.

Everything here is pure and fast (no model call, no network). The policy is deliberately conservative, because
measured speech recognition of one-word answers is unreliable: "Sí" came back as English, Danish or "See you", and
"Sim" as Russian. So a call only changes language on an utterance long enough to be confident, and keeps the current
language for short or ambiguous ones.

Matching runs on accent-stripped, lower-case text, so "audífonos", "Sí" and "não" need no special handling. Hindi
(Devanagari) keeps its vowel and nukta marks, which are part of the letters, and is recognised by its script.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .agent_config import LANGUAGES

# Groq returns spelled-out names ("Spanish"); other services return codes. Anything else (Danish, Russian...) is unsupported.
_NAMES = {
    "english": "en", "en": "en",
    "spanish": "es", "es": "es", "espanol": "es", "castellano": "es",
    "portuguese": "pt", "pt": "pt", "portugues": "pt",
    "hindi": "hi", "hi": "hi",
}
# \w does not match Devanagari vowel signs, so the Devanagari block is listed explicitly.
_WORD = re.compile(r"[\w\u0900-\u0963\u0966-\u097f]+", re.UNICODE)  # not the danda (U+0964), which ends a sentence
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")


def fold(text: str) -> str:
    """Lower-case and strip accents (Latin letters only: Devanagari virama and nukta are letters, not accents)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch) or _DEVANAGARI.match(ch))


def words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def normalize_language(value: Any) -> str | None:
    """"Spanish", "es", "es-MX" and "pt_BR" map to a supported code; anything else (or nothing) maps to None."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = fold(value.strip())
    return _NAMES.get(key) or _NAMES.get(re.split(r"[-_]", key)[0])


# Words that belong to exactly one of the three languages. Shared words ("no", "de", "pedido", "nunca", "esta", "que",
# "por", "mas", "para", "as") are left out on purpose.
_VOCAB = {
    "en": {
        "the", "my", "is", "it", "and", "never", "not", "was", "were", "have", "has", "this", "that", "with", "arrived",
        "package", "please", "would", "want", "like", "what", "you", "are", "but", "how", "when", "hello", "thanks",
        "thank", "yes", "wrong", "item", "order", "return", "damaged", "broken", "lost", "late", "refund",
    },
    "es": {
        "el", "los", "las", "un", "una", "del", "mi", "mis", "pero", "paquete", "llego", "quiero", "necesito",
        "gracias", "hola", "tambien", "tengo", "todavia", "aun", "enchufe", "roto", "rota", "con", "esto", "estoy",
        "fue", "llegado", "cuando", "donde", "pedidos", "correcto", "incorrecto", "exacto", "equivocado", "perfecto",
    },
    "pt": {
        "os", "um", "uma", "meu", "minha", "meus", "minhas", "nao", "pacote", "chegou", "quero", "preciso", "obrigado",
        "obrigada", "ola", "sim", "voce", "tambem", "tenho", "ainda", "tomada", "quebrado", "ele", "ela", "foi", "isso",
        "esse", "essa", "com", "estou", "ja", "correto", "incorreto", "exato", "errado", "perfeito",
    },
}
# Romanised Hindi ("Hinglish"). Whisper normally writes Hindi in Devanagari, which is recognised by script below, so
# this only matters for typed text. Short everyday words ("ka", "ko", "se", "hi") are left out: other languages use them.
_VOCAB["hi"] = {
    "mera", "meri", "mere", "nahi", "nahin", "abhi", "aaya", "aayi", "mujhe", "chahiye", "haan", "kripya",
    "dhanyavad", "namaste", "wapas", "karna", "yeh", "woh", "hai", "hain", "tak", "mera", "paas", "kaise",
}
_VOCAB["es"].discard("pedidos")  # "pedidos" is the same word in Spanish and Portuguese

# An unaccented "si" can mean "if", so a written Spanish yes counts as evidence only when it carries the accent.
_ACCENTED_ES_YES = re.compile(r"\bsí\b", re.IGNORECASE)


def detect_text_language(text: str) -> tuple[str | None, int]:
    """The clearly winning language of the text and its score, or (None, 0) when none stands out."""
    tokens = words(text)
    scores = {lang: sum(token in vocab for token in tokens) for lang, vocab in _VOCAB.items()}
    scores["hi"] += sum(1 for token in tokens if _DEVANAGARI.search(token))  # every Devanagari word is Hindi evidence
    if _ACCENTED_ES_YES.search(text):  # a written "sí" is Spanish evidence on top of the word lists
        scores["es"] += 1
    best = max(scores, key=scores.get)
    runner_up = sorted(scores.values())[-2]
    if scores[best] >= 1 and scores[best] > runner_up:
        return best, scores[best]
    return None, 0


# --- Explicit requests ("speak Spanish", "en español", "fale português") --------------------------------------------
_LANGUAGE_WORDS = {
    "en": re.compile(r"\b(?:english|ingles)\b"),
    "es": re.compile(r"\b(?:spanish|espanol|castellano|espanhol)\b"),
    "pt": re.compile(r"\b(?:portuguese|portugues)\b"),
    "hi": re.compile(fold(r"\bhindi\b|हिन्दी|हिंदी")),
}
# Hindi-script names for the other languages, so "अंग्रेज़ी में बात करें" (speak English) works from a Hindi call.
_LANGUAGE_WORDS["en"] = re.compile(_LANGUAGE_WORDS["en"].pattern + fold(r"|अंग्रेज़ी|अंग्रेजी|इंग्लिश"))
_LANGUAGE_WORDS["es"] = re.compile(_LANGUAGE_WORDS["es"].pattern + fold(r"|स्पैनिश|स्पेनिश"))
_LANGUAGE_WORDS["pt"] = re.compile(_LANGUAGE_WORDS["pt"].pattern + fold(r"|पुर्तगाली"))
_CUE = re.compile(
    r"\b(?:speak|talk|switch|change|use|prefer|want|hablar|habla|hablame|hablas|cambiar|cambia|cambiemos|puedes|"
    r"podemos|quiero|prefiero|falar|fale|fala|mude|mudar|trocar|troque|pode|prefiro|quero|please|favor|por|em|en|in|to)\b"
    + fold(r"|बात|बोल|कृपया|चाहिए|चाहता|चाहती|कीजिए|कीजिये|करें|करिए|में")
)


def explicit_language_request(text: str) -> str | None:
    """The language the customer asked for ("habla español", "in Portuguese please"), or None.

    Only short utterances count, so a complaint that merely mentions a language is not taken as a request.
    """
    folded = fold(text)
    if not 0 < len(_WORD.findall(folded)) <= 8 or not _CUE.search(folded):
        return None
    asked = [lang for lang, pattern in _LANGUAGE_WORDS.items() if pattern.search(folded)]
    return asked[0] if len(asked) == 1 else None


# --- The switch policy ---------------------------------------------------------------------------------------------
MIN_WORDS_TO_SWITCH = 3
CONFIDENT_WORDS = 5


def resolve_language(text: str, detected: str | None, current: str) -> str:
    """The language the call should use after this utterance. Keeps `current` unless the evidence is clear.

    detected is speech recognition's guess (None for typed text or an unsupported language). The rules:
    - one or two words ("sí", "ok", "sim"): never switch, however clear they sound; yes and no are understood in
      every language anyway, and a language change needs a customer to say more than a word;
    - three or more words: speech recognition and the word lists must not disagree, and the utterance must be
      long enough (five words) or carry at least two words exclusive to that language.
    """
    detected = detected if detected in LANGUAGES else None
    count = len(words(text))
    if count == 0:
        return current
    if count < MIN_WORDS_TO_SWITCH:
        return current

    winner, score = detect_text_language(text)
    candidate = None
    if detected is not None:
        if winner is None or winner == detected:
            candidate = detected if (count >= CONFIDENT_WORDS or score >= 2) else None
    elif winner is not None:
        candidate = winner if (count >= CONFIDENT_WORDS or score >= 2) else None
    return candidate if candidate in LANGUAGES else current


# --- Understanding the customer's words in each language -----------------------------------------------------------
# Used when the model is unavailable or unsure. Patterns run on accent-stripped lower-case text.
CASE_KEYWORDS = (
    (
        "DAMAGED_ON_ARRIVAL",
        re.compile(
            r"crack|broke|broken|damag|shatter|dent|smash|defect|scratch|doesn.t work|not working|dead on arrival|"
            r"\brot[oa]s?\b|danad|quebr|se rompio|agriet|golpe|abollad|no funciona|defectuos|"
            r"danificad|rachad|trincad|amassad|defeituos|nao funciona|veio quebrad|chegou quebrad"
        ),
    ),
    (
        "LATE_DELIVERY",
        re.compile(
            r"\blate\b|never (arrived|showed|came)|not arrived|hasn.t arrived|\blost\b|missing|delay|still waiting|"
            r"where is|tracking|didn.t (arrive|show)|"
            r"nunca llego|no llego|no ha llegado|no me llego|retras|perdid|extravi|sigue sin llegar|donde esta|rastreo|"
            r"seguimiento|\btarde\b|\btardo\b|"
            r"nunca chegou|nao chegou|ainda nao chegou|atras|extraviad|demor|onde esta|rastreio|rastreamento"
        ),
    ),
    (
        "RETURN_REQUEST",
        re.compile(
            r"\breturn|\brefund|send (it )?back|don.t want|changed my mind|doesn.t fit|not what i expected|"
            r"devolver|devolucion|reembolso|devuelv|cambie de opinion|no lo quiero|no me gusta|no me queda|no era lo que|"
            r"devolucao|estorno|mudei de ideia|nao quero|nao gostei|nao serve|nao era o que"
        ),
    ),
)

# Hindi has no \b-friendly word edges (vowel signs are not word characters), so yes and no are matched as whole tokens.
_HI_YES = {fold(w) for w in ("हाँ", "हां", "हा", "ठीक", "सही", "बिल्कुल", "बिलकुल", "जरूर", "ज़रूर", "haan", "theek", "sahi", "bilkul")}
_HI_NO = {fold(w) for w in ("नहीं", "नही", "नाही", "गलत", "ग़लत", "nahi", "nahin", "galat")}


_NEGATIVE = re.compile(
    r"\b(no|nope|nah|not|wrong|incorrect|change|different|actually|nao|incorrecto|incorreto|errado|equivocado|"
    r"cambiar|mudar|falso)\b|n't\b"
)
_POSITIVE = re.compile(
    r"\b(yes|yeah|yep|yup|correct|right|exactly|sure|ok|okay|absolutely|please|confirm|confirmed|go ahead|"
    r"si|claro|correcto|exacto|exactamente|vale|perfecto|adelante|confirmo|efectivamente|seguro|"
    r"sim|correto|certo|exato|perfeito|beleza)\b|asi es|de acuerdo|isso mesmo|com certeza|esta certo|esta correcto|pode (?:enviar|mandar|seguir|sim)"
)
_DOUBLE_NEGATIVE = re.compile(
    r"\bnot\s+(wrong|incorrect)\b|\bno\s+esta\s+(mal|incorrecto|equivocado)\b|\bnao\s+esta\s+(errado|incorreto)\b"
)


def interpret_yes_no(text: str) -> bool | None:
    """True for yes, False for no, None when unclear, mixed ("that's not right") or a double negative."""
    folded = fold(text)
    if _DOUBLE_NEGATIVE.search(folded):  # "that's not wrong" means yes; leave it to the model rather than guess
        return None
    spoken = set(words(text))
    negative = bool(_NEGATIVE.search(folded)) or bool(spoken & _HI_NO)
    positive = bool(_POSITIVE.search(folded)) or bool(spoken & _HI_YES)
    if negative and not positive:
        return False
    if positive and not negative:
        return True
    return None


# Hindi phrases, written the way Whisper writes them. Whisper often drops the nasal mark ("पहुचा" for "पहुँचा", "नही"
# for "नहीं"), so the optional [ंँ] makes both spellings match. No \b: it does not work next to Devanagari vowel signs.
_HI_CASE_KEYWORDS = {
    "DAMAGED_ON_ARRIVAL": re.compile(fold(
        r"toot|tuta|kharab|टूट|टुकड़े|खराब|ख़राब|क्षतिग्रस्त|फट|दरार|चटक|डैमेज|ब्रोकन|नुकसान|काम नही[ंँ]? कर|चल नही[ंँ]? रहा"
    )),
    "LATE_DELIVERY": re.compile(fold(
        r"nahi\w* (?:aaya|aayi|pahunch\w*|mila|mili)|abhi tak nahi|नही[ंँ]? (?:आया|आई|आये|आए|पहु|मिला|मिली)|पहु[ंँ]?च[ाी]? नही|आया नही|आई नही|मिला नही|अभी तक नही|"
        r"देर|लेट|गुम|खो गय|ट्रैकिंग|कहाँ है|कहां है|इंतज़ार|इंतजार|डिलीवर नही"
    )),
    "RETURN_REQUEST": re.compile(fold(
        r"wapas|vapas|वापस|लौटा|रिटर्न|रिफंड|रिफ़ंड|नही[ंँ]? चाहिए|पसंद नही|मन बदल|बदलना|साइज़|साइज|फिट नही|एक्सचेंज"
    )),
}


def keyword_case_type(text: str) -> str | None:
    """Fallback classifier for the customer's issue in any supported language."""
    folded = fold(text)
    for case_type, pattern in CASE_KEYWORDS:
        if pattern.search(folded) or _HI_CASE_KEYWORDS[case_type].search(folded):
            return case_type
    return None
