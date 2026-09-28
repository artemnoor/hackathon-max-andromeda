"""Transparent, versioned rules for the first semantic taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SemanticRule:
    rule_id: str
    feature_code: str
    keywords: tuple[str, ...]
    value: Decimal
    confidence: Decimal
    rationale: str


def _rule(
    rule_id: str,
    feature_code: str,
    keywords: tuple[str, ...],
    value: str,
    confidence: str,
    rationale: str,
) -> SemanticRule:
    return SemanticRule(
        rule_id=rule_id,
        feature_code=feature_code,
        keywords=keywords,
        value=Decimal(value),
        confidence=Decimal(confidence),
        rationale=rationale,
    )


DEFAULT_SEMANTIC_RULES: tuple[SemanticRule, ...] = (
    _rule("subject:mathematics", "mathematics", ("математ", "матан", "calculus", "linear algebra", "мат. анализ"), "0.90", "0.90", "Название прямо указывает на математическое содержание."),
    _rule("subject:statistics", "statistics", ("статист", "вероятн", "probability", "statistics", "эконометрик"), "0.88", "0.88", "Название содержит статистический или вероятностный термин."),
    _rule("subject:programming", "programming", ("программирован", "программн", "кодирован", "software development", "python", "java", "c++", "javascript"), "0.90", "0.87", "Название указывает на разработку программ или языки программирования."),
    _rule("subject:computer-science", "computer_science", ("информатик", "computer science", "вычислительн", "алгоритм", "операционн систем", "компьютерн сет"), "0.82", "0.84", "Название указывает на фундаментальную область компьютерных наук."),
    _rule("subject:data", "data", ("данн", "баз данн", "data", "sql", "data mining", "хранилищ"), "0.84", "0.84", "Название связано с данными, базами или хранилищами."),
    _rule("subject:algorithms", "algorithms", ("алгоритм", "algorithm"), "0.88", "0.86", "Название прямо указывает на алгоритмическое содержание."),
    _rule("subject:databases", "databases", ("баз данн", "database", "sql", "хранилищ"), "0.88", "0.86", "Название указывает на базы данных или хранилища."),
    _rule("subject:information-systems", "information_systems", ("информационн систем", "information system", "erp", "корпоративн систем"), "0.82", "0.80", "Название связано с информационными системами."),
    _rule("skill:data-analysis", "data_analysis", ("анализ данн", "data analysis", "data analytics", "аналитик данн"), "0.90", "0.87", "Название указывает на анализ данных."),
    _rule("subject:ai-ml", "ai_ml", ("машинн обуч", "машинное обуч", "нейросет", "искусственн интеллект", "machine learning", "deep learning", "computer vision", "обучен с подкреплен", "nlp"), "0.96", "0.93", "Название содержит прямой термин AI или машинного обучения."),
    _rule("subject:cybersecurity", "cybersecurity", ("кибербезопас", "информационн безопас", "защит информац", "cybersecurity", "security"), "0.92", "0.88", "Название указывает на защиту информации или систем."),
    _rule("subject:calculus", "calculus", ("матан", "математическ анализ", "calculus", "дифференциальн исчислен"), "0.92", "0.88", "Название указывает на математический анализ."),
    _rule("subject:linear-algebra", "linear_algebra", ("линейн алгебр", "linear algebra", "матриц"), "0.92", "0.88", "Название указывает на линейную алгебру."),
    _rule("subject:discrete-math", "discrete_math", ("дискретн математик", "дискретн структ"), "0.90", "0.86", "Название указывает на дискретную математику."),
    _rule("subject:probability", "probability", ("вероятн", "probability", "случайн процесс"), "0.90", "0.86", "Название указывает на вероятностные модели."),
    _rule("subject:optimization", "optimization", ("оптимизац", "optimization", "исследовани операц"), "0.88", "0.84", "Название указывает на оптимизационные методы."),
    _rule("subject:physics", "physics", ("физик", "квантов", "оптик", "механик", "термодинамик", "physics"), "0.90", "0.89", "Название указывает на физическое содержание."),
    _rule("subject:mechanics", "mechanics", ("механик", "mechanics", "теоретическ механик"), "0.88", "0.84", "Название указывает на механику."),
    _rule("subject:electronics", "electronics", ("электрон", "электротехник", "схемотехник", "electronics"), "0.88", "0.84", "Название указывает на электронику или схемы."),
    _rule("subject:engineering", "engineering", ("инженер", "конструирован", "машиностроен", "электротехник", "схемотехник", "мехатрон", "робототехник", "проектирован"), "0.86", "0.84", "Название указывает на инженерное проектирование или технологию."),
    _rule("subject:business", "business", ("бизнес", "предпринимател", "business", "стартап", "коммерц"), "0.84", "0.82", "Название связано с бизнесом или предпринимательством."),
    _rule("subject:management", "management", ("менеджмент", "управлен", "management", "управление проект"), "0.84", "0.84", "Название связано с управлением."),
    _rule("subject:economics", "economics", ("экономик", "эконометр", "экономическ", "economics"), "0.88", "0.88", "Название содержит экономический термин."),
    _rule("subject:finance", "finance", ("финанс", "инвестиц", "банковск", "finance", "бухгалтер"), "0.88", "0.87", "Название связано с финансами, инвестициями или банковским делом."),
    _rule("subject:linguistics", "linguistics", ("лингвист", "языкозн", "язык", "филолог", "linguistics"), "0.86", "0.84", "Название связано с языком или лингвистикой."),
    _rule("subject:design", "design", ("дизайн", "design", "графическ", "визуальн", "интерфейс"), "0.86", "0.84", "Название связано с дизайном или визуальным проектированием."),
    _rule("subject:law", "law", ("право", "юридическ", "law"), "0.90", "0.86", "Название указывает на правовое содержание."),
    _rule("activity:research", "research", ("исследован", "научн", "research", "академическ", "методолог"), "0.78", "0.78", "Название указывает на исследовательскую деятельность."),
    _rule("skill:analytics", "analytics", ("аналитик", "анализ данн", "системн анализ", "analytics", "исследовани операц"), "0.82", "0.81", "Название указывает на аналитическую работу."),
    _rule("style:theory", "theory", ("теори", "теоретическ", "математическ основы", "основы математическ"), "0.76", "0.76", "Название указывает на теоретический уклон."),
    _rule("style:practice", "practice", ("практикум", "практик", "стажировк", "прикладн", "лабораторн", "practice"), "0.74", "0.74", "Название указывает на практическую деятельность."),
    _rule("style:theoretical", "theoretical", ("теори", "теоретическ"), "0.78", "0.76", "Название указывает на теоретическую направленность."),
    _rule("style:practical", "practical", ("практик", "прикладн", "стажировк", "лабораторн"), "0.78", "0.76", "Название указывает на практическую направленность."),
    _rule("activity:project-work", "project_work", ("проектн", "курсовой проект", "проектирован", "project", "capstone"), "0.82", "0.80", "Название указывает на проектную работу."),
    _rule("skill:communication", "communication", ("коммуникац", "риторик", "презентац", "переговор", "communication", "публичн выступлен"), "0.80", "0.79", "Название связано с коммуникацией и презентацией."),
)


__all__ = ["DEFAULT_SEMANTIC_RULES", "SemanticRule"]
