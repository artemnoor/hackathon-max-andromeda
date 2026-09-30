from __future__ import annotations

import re

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

_AREA_ALIASES: dict[DisciplineAreaCode, tuple[str, ...]] = {
    DisciplineAreaCode.MATHEMATICS_STATISTICS: ("математ", "матан", "статистик", "вычислен"),
    DisciplineAreaCode.COMPUTER_SCIENCE_DATA: (
        "искусственн интеллект", "машинн обучен", "data science", "айти",
        "программирован", "разработк", "информатик", "компьютерн наук",
        "работа с данными", "данными", "ии", "ai", "it",
    ),
    DisciplineAreaCode.PHYSICS_ASTRONOMY: ("физик", "астроном"),
    DisciplineAreaCode.CHEMISTRY_MATERIALS: ("хими", "материаловед"),
    DisciplineAreaCode.BIOLOGY_BIOTECHNOLOGY: ("биолог", "биотехнолог"),
    DisciplineAreaCode.EARTH_ENVIRONMENT: ("эколог", "климат", "геолог"),
    DisciplineAreaCode.ENGINEERING_TECHNOLOGY: ("инженер", "электроник", "железо", "робототех", "механик"),
    DisciplineAreaCode.ARCHITECTURE_CONSTRUCTION: ("архитект", "строительств", "bim"),
    DisciplineAreaCode.AGRICULTURE_VETERINARY: ("агроном", "ветеринар", "сельск хозяйств"),
    DisciplineAreaCode.MEDICINE_HEALTH: ("медицин", "здоров", "фармац", "лечить"),
    DisciplineAreaCode.PSYCHOLOGY_COGNITIVE: ("психолог", "когнитив"),
    DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES: ("социолог", "общественн наук"),
    DisciplineAreaCode.ECONOMICS_FINANCE: ("экономик", "финанс", "эконометрик"),
    DisciplineAreaCode.BUSINESS_MANAGEMENT: ("бизнес", "управлен", "менеджмент", "предпринимател"),
    DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION: ("право", "юриспруден", "государственн управлен"),
    DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE: ("язык", "лингвист", "литератур", "перевод"),
    DisciplineAreaCode.HISTORY_PHILOSOPHY_HUMANITIES: ("истори", "философ", "гуманитар"),
    DisciplineAreaCode.ART_DESIGN_MEDIA: ("дизайн", "искусств", "медиа", "журналист", "коммуникац"),
    DisciplineAreaCode.EDUCATION_PEDAGOGY: ("педагог", "образован", "преподаван", "учитель"),
    DisciplineAreaCode.SPORT_TOURISM_HOSPITALITY: ("спорт", "туризм", "гостиниц", "ресторан"),
    DisciplineAreaCode.SAFETY_DEFENSE_TRANSPORT: ("безопасност", "оборона", "транспорт", "навигац"),
    DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY: ("междисциплинар", "проектн деятельност"),
}

_NEGATIVE_CUE = re.compile(
    r"не\s+(?:хочу|люблю|нравится|интересует|подходит)|"
    r"без|поменьше|меньше|не\s+слишком|избегать|не\s+хотелось\s+бы|"
    r"терпеть\s+не\s+могу|ненавиж\w*",
)
_POSITIVE_CUE = re.compile(
    r"нрав\w*|интерес\w*|люб\w*|увлека\w*|предпочита\w*|"
    r"хочу\s+(?:изучать|заниматься|в\s+(?:айти|it))|по\s+душе|"
    r"верн\w*\s+(?:к|на)|около",
)
_CLAUSE_BOUNDARY = re.compile(r"[,;.!?]|\b(?:но|однако)\b")


def extract_explicit_area_preferences(
    text: str, *, infer_from_area_mention: bool = False
) -> tuple[tuple[DisciplineAreaCode, ...], tuple[DisciplineAreaCode, ...]]:
    """Extract only area mentions grounded in this turn and local preference cues."""

    normalized = " ".join(text.casefold().replace("ё", "е").split())
    preferred: list[DisciplineAreaCode] = []
    avoided: list[DisciplineAreaCode] = []
    for area, aliases in _AREA_ALIASES.items():
        occurrences = tuple(
            match
            for alias in aliases
            for match in _alias_matches(alias, normalized)
        )
        if not occurrences:
            continue
        sentiments = tuple(_occurrence_sentiment(match, normalized) for match in occurrences)
        if any(negative for negative, _ in sentiments):
            avoided.append(area)
        elif infer_from_area_mention or any(positive for _, positive in sentiments):
            preferred.append(area)
    return tuple(preferred), tuple(avoided)


def area_is_in_text(area: DisciplineAreaCode, normalized_text: str) -> bool:
    return any(_alias_matches(alias, normalized_text) for alias in _AREA_ALIASES[area])


def area_is_explicitly_avoided(area: DisciplineAreaCode, normalized_text: str) -> bool:
    return any(
        negative
        for alias in _AREA_ALIASES[area]
        for match in _alias_matches(alias, normalized_text)
        for negative, _ in (_occurrence_sentiment(match, normalized_text),)
    )


def _alias_matches(alias: str, text: str) -> tuple[re.Match[str], ...]:
    if alias in {"ии", "ai", "it", "bim"}:
        return tuple(re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", text))
    parts = tuple(_alias_token_stem(token) for token in alias.split())
    pattern = r"(?<!\w)" + r"\s+".join(
        re.escape(part) + r"\w*" for part in parts
    ) + r"(?!\w)"
    return tuple(re.finditer(pattern, text))


def _alias_token_stem(token: str) -> str:
    for suffix in (
        "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
        "иях", "ах", "ях", "ам", "ям", "ов", "ев", "ом", "ем", "ой",
        "ый", "ий", "ая", "яя", "ое", "ее", "а", "я", "е", "и", "у", "ю", "о",
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _occurrence_sentiment(match: re.Match[str], text: str) -> tuple[bool, bool]:
    left = text[max(0, match.start() - 64) : match.start()]
    right = text[match.end() : min(len(text), match.end() + 40)]
    left = _CLAUSE_BOUNDARY.split(left)[-1]
    right = _CLAUSE_BOUNDARY.split(right, maxsplit=1)[0]
    local = f"{left} {right}"
    negative = _NEGATIVE_CUE.search(local) is not None
    positive = _POSITIVE_CUE.search(local) is not None
    return negative, positive and not negative
