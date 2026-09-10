"""Language table, stopword gate data and per-language chat-slang hints."""

# (code, English name). "auto" is only valid as the chat language.
LANGUAGES = [
    ("auto", "Auto-detect"),
    ("en", "English"),
    ("nl", "Dutch"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("pl", "Polish"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("no", "Norwegian"),
    ("fi", "Finnish"),
    ("cs", "Czech"),
    ("tr", "Turkish"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
]

_BY_CODE = dict(LANGUAGES)
_BY_NAME = {name: code for code, name in LANGUAGES}


def name_for(code):
    return _BY_CODE.get(code, code)


def code_for(name):
    return _BY_NAME.get(name, name)


def choices(include_auto=True):
    return [name for code, name in LANGUAGES if include_auto or code != "auto"]


# High-frequency words, used only as a cheap gate so lines already in the
# reader's own language never reach the model. Languages missing from this
# table simply always get translated.
STOPWORDS = {
    "en": {
        "the", "is", "are", "was", "were", "you", "your", "we", "they", "this",
        "that", "there", "here", "what", "why", "how", "when", "who", "need",
        "want", "have", "has", "will", "would", "can", "could", "should",
        "please", "thanks", "anyone", "someone", "looking", "still", "just",
        "with", "for", "and", "but", "not", "know", "think", "make", "take",
        "come", "going", "does", "did", "get", "got", "any", "all", "from",
    },
    "nl": {
        "de", "het", "een", "en", "van", "ik", "je", "jij", "hij", "zij", "wij",
        "niet", "wel", "is", "zijn", "was", "heb", "hebt", "heeft", "hebben",
        "doe", "doen", "gaan", "ga", "gaat", "komt", "kom", "komen", "kan",
        "kun", "kunt", "kunnen", "moet", "moeten", "wil", "wilt", "willen",
        "mag", "wat", "wie", "waar", "waarom", "hoe", "wanneer", "welke",
        "dit", "dat", "deze", "die", "hier", "daar", "nog", "maar", "want",
        "omdat", "als", "dan", "ook", "even", "ff", "idd", "gwn", "kdenk",
        "mss", "ipv", "aub", "zsm", "wrm", "nee", "ja", "jou", "jullie",
        "mijn", "jouw", "onze", "iemand", "niemand", "iedereen", "alles",
        "niets", "veel", "weinig", "goed", "slecht", "snel", "klaar", "bezig",
        "wacht", "wachten", "nodig", "samen", "straks", "morgen", "vandaag",
        "altijd", "nooit", "misschien", "graag", "bedankt", "dank", "hallo",
        "hoi", "doei", "gilde", "spelen", "speel", "zoek", "zoeken", "helpen",
        "help", "beter", "sorry", "geen", "meer", "met", "voor", "naar",
        "over", "onder", "tussen", "zonder", "door",
    },
    "de": {
        "der", "die", "das", "und", "ist", "nicht", "ich", "du", "wir", "ihr",
        "sie", "ein", "eine", "einen", "mit", "auf", "für", "von", "zu", "im",
        "kann", "muss", "will", "hat", "haben", "war", "wird", "noch", "auch",
        "aber", "oder", "wenn", "was", "wer", "wo", "wie", "warum", "bitte",
        "danke", "jemand", "brauche", "suche", "gerne", "schnell", "immer",
        "nie", "gut", "schlecht", "hier", "dort", "jetzt", "heute", "morgen",
    },
    "fr": {
        "le", "la", "les", "un", "une", "des", "et", "est", "sont", "je",
        "tu", "il", "elle", "nous", "vous", "ils", "pas", "ne", "que", "qui",
        "quoi", "pour", "avec", "sur", "dans", "mais", "ou", "donc", "aussi",
        "très", "bien", "merci", "salut", "besoin", "cherche", "peux", "peut",
        "veux", "veut", "faire", "aller", "tout", "plus", "moins", "encore",
    },
    "es": {
        "el", "la", "los", "las", "un", "una", "y", "es", "son", "no", "que",
        "de", "en", "por", "para", "con", "yo", "tu", "él", "ella", "nosotros",
        "pero", "como", "cuando", "donde", "quien", "gracias", "hola", "por favor",
        "necesito", "busco", "puedo", "puede", "quiero", "hacer", "muy", "más",
        "todo", "nada", "bien", "mal", "ahora", "hoy", "mañana", "siempre",
    },
    "it": {
        "il", "lo", "la", "i", "gli", "le", "un", "una", "e", "è", "sono",
        "non", "che", "di", "in", "per", "con", "io", "tu", "lui", "lei",
        "noi", "voi", "ma", "come", "quando", "dove", "chi", "grazie", "ciao",
        "serve", "cerco", "posso", "può", "voglio", "fare", "molto", "più",
        "tutto", "niente", "bene", "male", "adesso", "oggi", "domani", "sempre",
    },
    "pt": {
        "o", "a", "os", "as", "um", "uma", "e", "é", "são", "não", "que",
        "de", "em", "por", "para", "com", "eu", "tu", "ele", "ela", "nós",
        "mas", "como", "quando", "onde", "quem", "obrigado", "olá", "preciso",
        "procuro", "posso", "pode", "quero", "fazer", "muito", "mais", "tudo",
        "nada", "bem", "mal", "agora", "hoje", "amanhã", "sempre",
    },
    "pl": {
        "nie", "tak", "jest", "sie", "się", "to", "co", "kto", "gdzie", "jak",
        "dlaczego", "kiedy", "ale", "czy", "juz", "już", "jeszcze", "tez",
        "też", "bardzo", "dobrze", "zle", "źle", "dzieki", "dzięki", "czesc",
        "cześć", "prosze", "proszę", "szukam", "potrzebuje", "potrzebuję",
        "moge", "mogę", "chce", "chcę", "masz", "mam", "jestem", "bedzie",
        "będzie", "teraz", "dzisiaj", "jutro", "zawsze", "nigdy", "kto",
    },
    "ru": {
        "не", "да", "нет", "это", "что", "кто", "где", "как", "почему",
        "когда", "но", "или", "уже", "еще", "ещё", "тоже", "очень", "хорошо",
        "плохо", "спасибо", "привет", "пожалуйста", "ищу", "нужно", "надо",
        "могу", "хочу", "есть", "быть", "будет", "сейчас", "сегодня",
        "завтра", "всегда", "никогда", "мне", "тебе", "меня", "тебя", "мы",
        "вы", "они", "он", "она", "и", "в", "на", "с", "по", "за", "до",
    },
    "uk": {
        "не", "так", "ні", "це", "що", "хто", "де", "як", "чому", "коли",
        "але", "або", "вже", "ще", "теж", "дуже", "добре", "погано", "дякую",
        "привіт", "будь ласка", "шукаю", "треба", "можу", "хочу", "є",
        "буде", "зараз", "сьогодні", "завтра", "завжди", "ніколи", "мене",
        "тебе", "ми", "ви", "вони", "він", "вона", "і", "в", "на", "з",
    },
    "sv": {
        "och", "att", "det", "som", "en", "ett", "inte", "har", "jag", "du",
        "vi", "han", "hon", "de", "för", "med", "på", "av", "till", "men",
        "eller", "vad", "vem", "var", "hur", "varför", "när", "tack", "hej",
        "behöver", "söker", "kan", "vill", "göra", "mycket", "bra", "dålig",
        "nu", "idag", "imorgon", "alltid", "aldrig", "kanske", "snälla",
    },
    "da": {
        "og", "at", "det", "som", "en", "et", "ikke", "har", "jeg", "du",
        "vi", "han", "hun", "de", "for", "med", "på", "af", "til", "men",
        "eller", "hvad", "hvem", "hvor", "hvordan", "hvorfor", "hvornår",
        "tak", "hej", "brug", "søger", "kan", "vil", "gøre", "meget", "godt",
        "nu", "idag", "imorgen", "altid", "aldrig", "måske",
    },
    "no": {
        "og", "at", "det", "som", "en", "et", "ikke", "har", "jeg", "du",
        "vi", "han", "hun", "de", "for", "med", "på", "av", "til", "men",
        "eller", "hva", "hvem", "hvor", "hvordan", "hvorfor", "når", "takk",
        "hei", "trenger", "søker", "kan", "vil", "gjøre", "mye", "bra",
        "nå", "idag", "imorgen", "alltid", "aldri", "kanskje",
    },
    "fi": {
        "ja", "on", "ei", "että", "se", "mitä", "kuka", "missä", "miten",
        "miksi", "milloin", "mutta", "tai", "jo", "vielä", "myös", "todella",
        "hyvä", "huono", "kiitos", "moi", "tarvitsen", "etsin", "voin",
        "haluan", "tehdä", "nyt", "tänään", "huomenna", "aina", "ei koskaan",
    },
    "cs": {
        "ne", "ano", "je", "to", "co", "kdo", "kde", "jak", "proč", "kdy",
        "ale", "nebo", "už", "ještě", "také", "velmi", "dobře", "špatně",
        "díky", "ahoj", "prosím", "hledám", "potřebuji", "můžu", "chci",
        "být", "bude", "teď", "dnes", "zítra", "vždy", "nikdy",
    },
    "tr": {
        "ve", "bir", "bu", "ne", "kim", "nerede", "nasıl", "neden", "ama",
        "veya", "çok", "iyi", "kötü", "teşekkürler", "merhaba", "lütfen",
        "arıyorum", "lazım", "var", "yok", "şimdi", "bugün", "yarın",
        "her zaman", "asla", "için", "ile", "değil", "evet", "hayır",
    },
}

# Extra prompt lines for languages whose chat slang trips small models up.
SLANG_HINTS = {
    "nl": (
        "Dutch chat slang you will see: ff = just/a sec, idd = indeed, "
        "gwn = just, kdenk = i think, wrm = why, ipv = instead of, "
        "mss = maybe, aub = please, zsm = asap, kzie = i see, nee = no, "
        "ja = yes, wacht = wait, kom = come, ga = go, moet = must, "
        "kan = can, nog = still/more."
    ),
    "de": (
        "German chat slang: bb = bis bald, hdf, ka = keine Ahnung, "
        "vllt = vielleicht, ne? = right?, iwie = irgendwie."
    ),
    "fr": (
        "French chat slang: slt = salut, pk/pq = pourquoi, jsp = je sais pas, "
        "dsl = désolé, stp = s'il te plaît, mdr = lol."
    ),
    "es": (
        "Spanish chat slang: xq/pq = por qué, tb = también, xfa = por favor, "
        "q = que, salu2 = saludos."
    ),
    "pl": (
        "Polish chat slang: nwm = nie wiem, spoko = ok, dzieki = thanks, "
        "zaraz = in a moment, jbc = just in case."
    ),
    "ru": (
        "Russian chat slang: спс = спасибо, пж = пожалуйста, норм = нормально, "
        "щас = сейчас, инв = invite, го = let's go."
    ),
}
