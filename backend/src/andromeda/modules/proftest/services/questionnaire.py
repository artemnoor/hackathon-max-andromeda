"""Deterministic, scenario-based questionnaire for educational content fit."""

from __future__ import annotations

from decimal import Decimal
import logging

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

from ..contracts.public import ActivityCode, Question, QuestionBlock, QuestionComponentType, QuestionOption, Questionnaire, QuestionStage


logger = logging.getLogger("andromeda.proftest.questionnaire")


def _option(
    option_id: str,
    label: str,
    *,
    subjects: tuple[tuple[DisciplineAreaCode, str], ...] = (),
    activities: tuple[tuple[ActivityCode, str], ...] = (),
    anti: tuple[tuple[DisciplineAreaCode, str], ...] = (),
    context: tuple[str, ...] = (),
    filters: tuple[str, ...] = (),
    formats: tuple[str, ...] = (),
) -> QuestionOption:
    return QuestionOption(
        id=option_id,
        label=label,
        subject_weights={area: Decimal(weight) for area, weight in subjects},
        activity_weights={activity: Decimal(weight) for activity, weight in activities},
        anti_interest_weights={area: Decimal(weight) for area, weight in anti},
        context_tags=context,
        filter_tags=filters,
        format_tags=formats,
    )


def build_questionnaire() -> Questionnaire:
    """Return a fresh questionnaire contract for every request."""

    return Questionnaire.from_questions(
        (
            Question(
                id="interest_free_day",
                block=QuestionBlock.INTERESTS,
                prompt="У тебя есть свободный день для проекта. Что интереснее?",
                options=(
                    _option("software_tool", "Собрать цифровой инструмент", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),), activities=((ActivityCode.SOFTWARE_CREATION, "1"),)),
                    _option("physical_device", "Разобраться, как работает устройство", subjects=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.7"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.3")), activities=((ActivityCode.PHYSICAL_ENGINEERING, "1"),)),
                    _option("data_story", "Найти закономерность в данных", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.5")), activities=((ActivityCode.DATA, "1"),)),
                    _option("product_concept", "Придумать, как улучшить продукт", subjects=((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.7"), (DisciplineAreaCode.ART_DESIGN_MEDIA, "0.3")), activities=((ActivityCode.CREATIVE, "0.7"), (ActivityCode.BUSINESS, "0.3"))),
                ),
            ),
            Question(
                id="interest_investigation",
                block=QuestionBlock.INTERESTS,
                prompt="Какая задача кажется тебе наиболее увлекательной?",
                options=(
                    _option("prove_model", "Проверить модель расчётами", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1"),), activities=((ActivityCode.ANALYTICAL, "1"),)),
                    _option("understand_nature", "Понять, почему происходит явление", subjects=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.8"), (DisciplineAreaCode.CHEMISTRY_MATERIALS, "0.2")), activities=((ActivityCode.RESEARCH, "1"),)),
                    _option("understand_people", "Понять, как люди принимают решения", subjects=((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.7"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.3")), activities=((ActivityCode.RESEARCH, "0.7"), (ActivityCode.COMMUNICATION, "0.3"))),
                    _option("tell_clearly", "Объяснить сложную идею понятным языком", subjects=((DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, "0.6"), (DisciplineAreaCode.EDUCATION_PEDAGOGY, "0.4")), activities=((ActivityCode.COMMUNICATION, "1"),)),
                ),
            ),
            Question(
                id="activity_build",
                block=QuestionBlock.ACTIVITIES,
                prompt="Какой результат работы тебе приятнее увидеть?",
                options=(
                    _option("working_code", "Работающий код или сервис", activities=((ActivityCode.SOFTWARE_CREATION, "1"),)),
                    _option("system_scheme", "Продуманную схему системы", activities=((ActivityCode.SYSTEM_DESIGN, "1"),)),
                    _option("tested_hypothesis", "Подтверждённую гипотезу", activities=((ActivityCode.RESEARCH, "0.6"), (ActivityCode.ANALYTICAL, "0.4"),)),
                    _option("visible_concept", "Визуальную концепцию или макет", activities=((ActivityCode.CREATIVE, "1"),)),
                ),
            ),
            Question(
                id="activity_working_style",
                block=QuestionBlock.ACTIVITIES,
                prompt="В командном проекте тебе ближе какая роль?",
                options=(
                    _option("organize_work", "Собрать план и организовать работу", activities=((ActivityCode.BUSINESS, "1"),)),
                    _option("analyze_options", "Сравнить варианты и найти лучшее решение", activities=((ActivityCode.ANALYTICAL, "1"),)),
                    _option("design_architecture", "Спроектировать устройство или систему", activities=((ActivityCode.SYSTEM_DESIGN, "0.7"), (ActivityCode.PHYSICAL_ENGINEERING, "0.3"))),
                    _option("explain_to_team", "Синхронизировать людей и объяснить идею", activities=((ActivityCode.COMMUNICATION, "1"),)),
                ),
            ),
            Question(
                id="anti_subjects",
                block=QuestionBlock.ANTI_INTERESTS,
                prompt="Какие области ты точно не хотел бы изучать много? Можно выбрать до трёх.",
                multi_select=True,
                max_selected=3,
                options=(
                    _option("avoid_physics", "Физика и физические системы", anti=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "1"),)),
                    _option("avoid_chemistry", "Химия и материалы", anti=((DisciplineAreaCode.CHEMISTRY_MATERIALS, "1"),)),
                    _option("avoid_programming", "Программирование и цифровые системы", anti=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),)),
                    _option("avoid_math", "Большой объём математики", anti=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1"),)),
                    _option("avoid_business", "Экономика и управление", anti=((DisciplineAreaCode.ECONOMICS_FINANCE, "0.6"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.4"))),
                    _option("avoid_humanities", "Языки и гуманитарные дисциплины", anti=((DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, "0.6"), (DisciplineAreaCode.HISTORY_PHILOSOPHY_HUMANITIES, "0.4"))),
                ),
            ),
            Question(
                id="activity_depth",
                block=QuestionBlock.ACTIVITIES,
                prompt="Какой темп и формат обучения тебе ближе?",
                options=(
                    _option("deep_theory", "Разобраться в принципах и доказательствах", activities=((ActivityCode.RESEARCH, "0.6"), (ActivityCode.ANALYTICAL, "0.4")), subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.6"),)),
                    _option("practical_prototype", "Быстро собрать прототип и проверить его", activities=((ActivityCode.SOFTWARE_CREATION, "0.4"), (ActivityCode.SYSTEM_DESIGN, "0.6"))),
                    _option("physical_experiment", "Поставить эксперимент с реальным объектом", activities=((ActivityCode.PHYSICAL_ENGINEERING, "0.7"), (ActivityCode.RESEARCH, "0.3"))),
                    _option("team_case", "Решить задачу через обсуждение и командный кейс", activities=((ActivityCode.COMMUNICATION, "0.5"), (ActivityCode.BUSINESS, "0.5"))),
                ),
            ),
        )
    )


def build_session_questionnaire_v2() -> Questionnaire:
    """Return the immutable v2 core used by resumable sessions.

    The legacy 24-question questionnaire is intentionally retained as the v2
    compatibility surface for existing API clients. This catalogue contains
    no program IDs and is deterministic; branching is applied by the session
    service using the saved answer state.
    """

    def question(
        question_id: str,
        block: QuestionBlock,
        stage: QuestionStage,
        component: QuestionComponentType,
        prompt: str,
        options: tuple[QuestionOption, ...],
        *,
        order: int,
        multi_select: bool = False,
        max_selected: int = 1,
        required: bool = True,
        allow_uncertain: bool = True,
        allow_skip: bool = False,
        dimensions: tuple[str, ...] = (),
    ) -> Question:
        return Question(
            id=question_id,
            block=block,
            stage=stage,
            component_type=component,
            order=order,
            prompt=prompt,
            options=options,
            required=required,
            allow_uncertain=allow_uncertain,
            allow_skip=allow_skip,
            multi_select=multi_select,
            max_selected=max_selected,
            declared_dimensions=dimensions,
        )

    questionnaire = Questionnaire.from_questions(
        (
            question("context_goal", QuestionBlock.CONTEXT, QuestionStage.ABOUT, QuestionComponentType.CHIP_SELECT, "Что сейчас важнее всего при выборе программы?", (
                _option("find_field", "Понять, какая область мне подходит", context=("exploration",)),
                _option("choose_program", "Сузить выбор конкретных программ", context=("selection",)),
                _option("check_fit", "Проверить уже понравившееся направление", context=("validation",)),
                _option("plan_future", "Разобраться с дальнейшими возможностями", context=("future",)),
            ), order=1, dimensions=("context",)),
            question("context_experience", QuestionBlock.CONTEXT, QuestionStage.ABOUT, QuestionComponentType.SINGLE_CHOICE, "Как ты сейчас ориентируешься в технических предметах?", (
                _option("new_to_field", "Пока только знакомлюсь", context=("beginner",)),
                _option("some_experience", "Пробовал(а) отдельные проекты или курсы", context=("early_experience",)),
                _option("confident", "Уже понимаю, что мне даётся", context=("experienced",)),
            ), order=2, dimensions=("context",)),
            question("seed_domains", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.CHIP_SELECT, "Какие области хочется попробовать? Можно выбрать несколько.", (
                _option("computers_data", "Компьютеры и данные", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),), activities=((ActivityCode.SOFTWARE_CREATION, "0.7"), (ActivityCode.DATA, "0.3"))),
                _option("math_logic", "Математика и логика", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1"),), activities=((ActivityCode.ANALYTICAL, "1"),)),
                _option("physics_devices", "Физика и устройства", subjects=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.7"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.3")), activities=((ActivityCode.PHYSICAL_ENGINEERING, "1"),)),
                _option("materials_chemistry", "Материалы и химические процессы", subjects=((DisciplineAreaCode.CHEMISTRY_MATERIALS, "1"),), activities=((ActivityCode.RESEARCH, "1"),)),
                _option("people_communication", "Люди и коммуникации", subjects=((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.5"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.5")), activities=((ActivityCode.COMMUNICATION, "1"),)),
                _option("business_products", "Бизнес и продукты", subjects=((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.6"), (DisciplineAreaCode.ECONOMICS_FINANCE, "0.4")), activities=((ActivityCode.BUSINESS, "1"),)),
            ), order=3, multi_select=True, max_selected=4, dimensions=("subject",)),
            question("interest_problem", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.SCENARIO_CHOICE, "Какую задачу интереснее довести до результата?", (
                _option("build_service", "Собрать сервис, которым воспользуются люди", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),), activities=((ActivityCode.SOFTWARE_CREATION, "0.7"), (ActivityCode.COMMUNICATION, "0.3"))),
                _option("explain_phenomenon", "Проверить гипотезу о явлении", subjects=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.5"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5")), activities=((ActivityCode.RESEARCH, "0.7"), (ActivityCode.ANALYTICAL, "0.3"))),
                _option("optimize_process", "Найти закономерность и улучшить процесс", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.6"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.4")), activities=((ActivityCode.DATA, "0.6"), (ActivityCode.BUSINESS, "0.4"))),
                _option("design_experience", "Продумать понятный интерфейс или опыт", subjects=((DisciplineAreaCode.ART_DESIGN_MEDIA, "0.7"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.3")), activities=((ActivityCode.CREATIVE, "0.8"), (ActivityCode.COMMUNICATION, "0.2"))),
            ), order=4, dimensions=("subject", "activity")),
            question("interest_math_logic", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.ANCHORED_SCALE, "Насколько тебе интересны задачи с расчётами и логикой?", (
                _option("not_for_me", "Скорее не моё"), _option("sometimes", "Зависит от задачи", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5"),), activities=((ActivityCode.ANALYTICAL, "0.5"),)), _option("very_interesting", "Очень интересно", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1"),), activities=((ActivityCode.ANALYTICAL, "1"),)),
            ), order=5, dimensions=("subject:mathematics",)),
            question("interest_software", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.SCENARIO_CHOICE, "Насколько тебе интересно создавать цифровые решения?", (
                _option("not_for_me" , "Скорее не моё"), _option("sometimes", "Иногда интересно", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.5"),), activities=((ActivityCode.SOFTWARE_CREATION, "0.5"),)), _option("very_interesting", "Хочу разбираться глубже", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),), activities=((ActivityCode.SOFTWARE_CREATION, "1"),)),
            ), order=6, dimensions=("subject:computer_science",)),
            question("interest_engineering", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.SCENARIO_CHOICE, "Насколько интересны реальные устройства и инженерные системы?", (
                _option("not_for_me", "Скорее не моё"), _option("sometimes", "Иногда интересно", subjects=((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.5"),), activities=((ActivityCode.PHYSICAL_ENGINEERING, "0.5"),)), _option("very_interesting", "Хочу собирать и проверять", subjects=((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.7"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.3")), activities=((ActivityCode.PHYSICAL_ENGINEERING, "1"),)),
            ), order=7, dimensions=("subject:engineering",)),
            question("interest_research", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.SCENARIO_CHOICE, "Насколько тебе нравится искать причины и проверять гипотезы?", (
                _option("not_for_me", "Скорее не моё"), _option("sometimes", "Иногда интересно", activities=((ActivityCode.RESEARCH, "0.5"),)), _option("very_interesting", "Это меня увлекает", activities=((ActivityCode.RESEARCH, "1"),), subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.5"))),
            ), order=8, dimensions=("activity:research",)),
            question("interest_people", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.ANCHORED_SCALE, "Насколько тебе важно учитывать людей и их опыт?", (
                _option("not_for_me", "Не главный фокус"), _option("sometimes", "Зависит от проекта", subjects=((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.5"),), activities=((ActivityCode.COMMUNICATION, "0.5"),)), _option("very_interesting", "Это важно для результата", subjects=((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.5"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.5")), activities=((ActivityCode.COMMUNICATION, "1"),)),
            ), order=9, dimensions=("activity:communication",)),
            question("interest_product", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.PAIR_CHOICE, "Что сильнее притягивает?", (
                _option("deep_technology", "Разобраться в технологии", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.6"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.4")), activities=((ActivityCode.RESEARCH, "0.5"), (ActivityCode.SYSTEM_DESIGN, "0.5"))),
                _option("useful_product", "Сделать полезный продукт", subjects=((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.5"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.5")), activities=((ActivityCode.BUSINESS, "0.5"), (ActivityCode.SOFTWARE_CREATION, "0.5"))),
            ), order=10, dimensions=("subject", "activity")),
            question("interest_broad_or_deep", QuestionBlock.INTERESTS, QuestionStage.INTERESTS, QuestionComponentType.PAIR_CHOICE, "Тебе ближе широкий обзор или глубокое погружение?", (
                _option("broad_view", "Увидеть систему целиком", activities=((ActivityCode.SYSTEM_DESIGN, "0.7"), (ActivityCode.COMMUNICATION, "0.3"))),
                _option("deep_dive", "Разобрать одну сложную задачу", activities=((ActivityCode.RESEARCH, "0.6"), (ActivityCode.ANALYTICAL, "0.4"))),
            ), order=11, dimensions=("activity",)),
            question("work_result", QuestionBlock.ACTIVITIES, QuestionStage.WORK_STYLE, QuestionComponentType.SCENARIO_CHOICE, "Какой результат работы хочется увидеть?", (
                _option("working_code", "Работающий код или сервис", activities=((ActivityCode.SOFTWARE_CREATION, "1"),)),
                _option("tested_device", "Проверенное устройство или прототип", activities=((ActivityCode.PHYSICAL_ENGINEERING, "1"),)),
                _option("clear_model", "Модель, расчёт или доказательство", activities=((ActivityCode.ANALYTICAL, "0.6"), (ActivityCode.RESEARCH, "0.4"))),
                _option("team_decision", "Согласованное решение команды", activities=((ActivityCode.COMMUNICATION, "0.6"), (ActivityCode.BUSINESS, "0.4"))),
            ), order=12, dimensions=("activity",)),
            question("work_role", QuestionBlock.ACTIVITIES, QuestionStage.WORK_STYLE, QuestionComponentType.CHIP_SELECT, "Какие роли хотелось бы попробовать? Можно несколько.", (
                _option("analyze", "Анализировать", activities=((ActivityCode.ANALYTICAL, "1"),)), _option("create", "Создавать", activities=((ActivityCode.SOFTWARE_CREATION, "0.7"), (ActivityCode.CREATIVE, "0.3"))), _option("design", "Проектировать", activities=((ActivityCode.SYSTEM_DESIGN, "1"),)), _option("research", "Исследовать", activities=((ActivityCode.RESEARCH, "1"),)), _option("communicate", "Объяснять", activities=((ActivityCode.COMMUNICATION, "1"),)), _option("organize", "Организовывать", activities=((ActivityCode.BUSINESS, "1"),)),
            ), order=13, multi_select=True, max_selected=3, dimensions=("activity",)),
            question("work_alone_team", QuestionBlock.ACTIVITIES, QuestionStage.WORK_STYLE, QuestionComponentType.PAIR_CHOICE, "В сложной задаче тебе комфортнее…", (
                _option("focus_alone", "Сначала самостоятельно разобраться", activities=((ActivityCode.ANALYTICAL, "0.6"), (ActivityCode.RESEARCH, "0.4")), formats=("individual_focus",)),
                _option("solve_together", "Сразу обсуждать с командой", activities=((ActivityCode.COMMUNICATION, "0.7"), (ActivityCode.SYSTEM_DESIGN, "0.3")), formats=("teamwork",)),
            ), order=14, dimensions=("activity", "format")),
            question("work_build_or_investigate", QuestionBlock.ACTIVITIES, QuestionStage.WORK_STYLE, QuestionComponentType.PAIR_CHOICE, "Что ближе в начале проекта?", (
                _option("build_first", "Быстро собрать первую версию", activities=((ActivityCode.SOFTWARE_CREATION, "0.6"), (ActivityCode.SYSTEM_DESIGN, "0.4")), formats=("hands_on",)),
                _option("investigate_first", "Сначала проверить предположения", activities=((ActivityCode.RESEARCH, "0.6"), (ActivityCode.ANALYTICAL, "0.4")), formats=("theory_first",)),
            ), order=15, dimensions=("activity", "format")),
            question("work_pace", QuestionBlock.ACTIVITIES, QuestionStage.WORK_STYLE, QuestionComponentType.ANCHORED_SCALE, "Какой темп тебе подходит?", (
                _option("steady", "Постепенно и основательно", formats=("steady",)), _option("mixed", "Чередовать глубину и практику", formats=("mixed",)), _option("fast_iterations", "Быстро пробовать и менять", formats=("iterative",)),
            ), order=16, dimensions=("format",)),
            question("work_uncertainty", QuestionBlock.ACTIVITIES, QuestionStage.WORK_STYLE, QuestionComponentType.ANCHORED_SCALE, "Как относишься к неопределённости в задаче?", (
                _option("clear_task", "Нужны понятные критерии", formats=("structured",)), _option("some_unknowns", "Нормально, если есть опора", formats=("guided",)), _option("explore_unknowns", "Интересно исследовать неизвестное", formats=("exploratory",)),
            ), order=17, dimensions=("format",)),
            question("anti_subjects_v2", QuestionBlock.ANTI_INTERESTS, QuestionStage.ANTI_INTERESTS, QuestionComponentType.MULTI_CHOICE, "Какие темы точно не хочется изучать много?", (
                _option("avoid_physics", "Физика и физические системы", anti=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "1"),)), _option("avoid_chemistry", "Химия и материалы", anti=((DisciplineAreaCode.CHEMISTRY_MATERIALS, "1"),)), _option("avoid_programming", "Программирование и цифровые системы", anti=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),)), _option("avoid_math", "Большой объём математики", anti=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1"),)), _option("avoid_business", "Экономика и управление", anti=((DisciplineAreaCode.ECONOMICS_FINANCE, "0.6"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.4"))), _option("avoid_people", "Коммуникации и социальные темы", anti=((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.5"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.5"))),
            ), order=18, multi_select=True, max_selected=3, dimensions=("anti_interest",)),
            question("anti_format", QuestionBlock.ANTI_INTERESTS, QuestionStage.ANTI_INTERESTS, QuestionComponentType.MULTI_CHOICE, "Что из формата обучения может утомлять?", (
                _option("many_exams", "Много экзаменов", anti=((DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.2"),), formats=("exam_heavy",)), _option("long_theory", "Долгие теоретические блоки", formats=("theory_heavy",)), _option("constant_teamwork", "Постоянная командная работа", formats=("team_heavy",)), _option("open_ended", "Задачи без чётких критериев", formats=("exploratory",)),
            ), order=19, multi_select=True, max_selected=2, dimensions=("format",)),
            question("anti_load", QuestionBlock.ANTI_INTERESTS, QuestionStage.ANTI_INTERESTS, QuestionComponentType.ANCHORED_SCALE, "Какой объём параллельных задач переносится комфортно?", (
                _option("low_load", "Лучше одна задача за раз", formats=("low_load",)), _option("balanced_load", "Несколько задач — нормально", formats=("balanced_load",)), _option("high_load", "Люблю плотный темп", formats=("high_load",)),
            ), order=20, dimensions=("load_tolerance",)),
            question("tradeoff_theory_practice", QuestionBlock.TRADE_OFFS, QuestionStage.TRADE_OFFS, QuestionComponentType.PAIR_CHOICE, "Если приходится выбирать, что важнее?", (
                _option("principles", "Понять принципы и основания", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.5")), activities=((ActivityCode.RESEARCH, "0.5"), (ActivityCode.ANALYTICAL, "0.5")), formats=("theory_first",)),
                _option("practice", "Сразу применить и проверить", activities=((ActivityCode.SOFTWARE_CREATION, "0.5"), (ActivityCode.PHYSICAL_ENGINEERING, "0.5")), formats=("hands_on",)),
            ), order=21, dimensions=("format", "activity")),
            question("tradeoff_precision_speed", QuestionBlock.TRADE_OFFS, QuestionStage.TRADE_OFFS, QuestionComponentType.PAIR_CHOICE, "Что ближе в проекте?", (
                _option("precision", "Дольше, но надёжнее", activities=((ActivityCode.ANALYTICAL, "0.7"), (ActivityCode.SYSTEM_DESIGN, "0.3")), formats=("steady",)), _option("speed", "Быстрее получить рабочий результат", activities=((ActivityCode.SOFTWARE_CREATION, "0.7"), (ActivityCode.BUSINESS, "0.3")), formats=("iterative",)),
            ), order=22, dimensions=("format",)),
            question("tradeoff_individual_team", QuestionBlock.TRADE_OFFS, QuestionStage.TRADE_OFFS, QuestionComponentType.PAIR_CHOICE, "Что сильнее влияет на удовольствие от работы?", (
                _option("individual_mastery", "Личный контроль над сложной задачей", activities=((ActivityCode.ANALYTICAL, "0.6"), (ActivityCode.RESEARCH, "0.4")), formats=("individual_focus",)), _option("team_impact", "Общий результат команды", activities=((ActivityCode.COMMUNICATION, "0.6"), (ActivityCode.BUSINESS, "0.4")), formats=("teamwork",)),
            ), order=23, dimensions=("format",)),
            question("tradeoff_stability_experiment", QuestionBlock.TRADE_OFFS, QuestionStage.TRADE_OFFS, QuestionComponentType.SCENARIO_CHOICE, "Представь выбор темы для проекта.", (
                _option("known_method", "Взять понятный метод и улучшить его", activities=((ActivityCode.SYSTEM_DESIGN, "0.6"), (ActivityCode.ANALYTICAL, "0.4")), formats=("structured",)), _option("new_method", "Попробовать новый подход с риском", activities=((ActivityCode.RESEARCH, "0.6"), (ActivityCode.CREATIVE, "0.4")), formats=("exploratory",)), _option("user_problem", "Начать с проблемы пользователя", activities=((ActivityCode.COMMUNICATION, "0.5"), (ActivityCode.BUSINESS, "0.5")), formats=("applied",)),
            ), order=24, dimensions=("format", "activity")),
        ),
        question_set_version="proftest-v2",
    )
    _log_resolved(questionnaire)
    return questionnaire


def build_session_questionnaire_v3() -> Questionnaire:
    """Return the compact five-question core for new resumable sessions.

    The options intentionally carry both subject and activity signals.  The
    session service can therefore build a useful preliminary profile before
    asking a bounded adaptive follow-up.
    """

    def question(
        question_id: str,
        block: QuestionBlock,
        stage: QuestionStage,
        component: QuestionComponentType,
        prompt: str,
        options: tuple[QuestionOption, ...],
        *,
        order: int,
        multi_select: bool = False,
        max_selected: int = 1,
        dimensions: tuple[str, ...] = (),
    ) -> Question:
        return Question(
            id=question_id,
            block=block,
            stage=stage,
            component_type=component,
            order=order,
            prompt=prompt,
            options=options,
            required=True,
            allow_uncertain=True,
            allow_skip=False,
            multi_select=multi_select,
            max_selected=max_selected,
            declared_dimensions=dimensions,
        )

    questionnaire = Questionnaire.from_questions(
        (
            question(
                "core_doing",
                QuestionBlock.INTERESTS,
                QuestionStage.INTERESTS,
                QuestionComponentType.MULTI_CHOICE,
                "Что из этого тебе действительно было бы интересно делать? Выбери максимум 3.",
                (
                    _option("software_systems", "Писать программы и разбираться в системах", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),), activities=((ActivityCode.SOFTWARE_CREATION, "0.7"), (ActivityCode.SYSTEM_DESIGN, "0.3"))),
                    _option("devices_mechanisms", "Проектировать устройства и механизмы", subjects=((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.6"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.4")), activities=((ActivityCode.PHYSICAL_ENGINEERING, "1"),)),
                    _option("data_patterns", "Анализировать данные и искать закономерности", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.5")), activities=((ActivityCode.DATA, "0.7"), (ActivityCode.ANALYTICAL, "0.3"))),
                    _option("physical_processes", "Исследовать физические процессы", subjects=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.8"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.2")), activities=((ActivityCode.RESEARCH, "0.8"), (ActivityCode.ANALYTICAL, "0.2"))),
                    _option("economics_business", "Работать с экономикой и бизнесом", subjects=((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.6"), (DisciplineAreaCode.ECONOMICS_FINANCE, "0.4")), activities=((ActivityCode.BUSINESS, "1"),)),
                    _option("people_products", "Создавать продукты для людей", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.3"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.3"), (DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.2"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.2")), activities=((ActivityCode.CREATIVE, "0.4"), (ActivityCode.COMMUNICATION, "0.3"), (ActivityCode.BUSINESS, "0.3"))),
                    _option("chemistry_materials", "Работать с химией и материалами", subjects=((DisciplineAreaCode.CHEMISTRY_MATERIALS, "1"),), activities=((ActivityCode.RESEARCH, "1"),)),
                    _option("dont_know", "Пока не знаю"),
                ),
                order=1,
                multi_select=True,
                max_selected=3,
                dimensions=("subject", "activity"),
            ),
            question(
                "core_learning",
                QuestionBlock.INTERESTS,
                QuestionStage.INTERESTS,
                QuestionComponentType.MULTI_CHOICE,
                "Что тебе интереснее изучать? Выбери до трёх областей.",
                (
                    _option("math_logic", "Математику и логику", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1"),), activities=((ActivityCode.ANALYTICAL, "1"),)),
                    _option("computers_data", "Компьютеры и данные", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),), activities=((ActivityCode.SOFTWARE_CREATION, "0.6"), (ActivityCode.DATA, "0.4"))),
                    _option("physics_devices", "Физику и устройства", subjects=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.7"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.3")), activities=((ActivityCode.PHYSICAL_ENGINEERING, "1"),)),
                    _option("chemistry_materials", "Химию и материалы", subjects=((DisciplineAreaCode.CHEMISTRY_MATERIALS, "0.8"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.2")), activities=((ActivityCode.RESEARCH, "1"),)),
                    _option("people_society", "Людей и общество", subjects=((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.5"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.5")), activities=((ActivityCode.COMMUNICATION, "1"),)),
                    _option("business_economics", "Бизнес и экономику", subjects=((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.5"), (DisciplineAreaCode.ECONOMICS_FINANCE, "0.5")), activities=((ActivityCode.BUSINESS, "1"),)),
                    _option("design_languages", "Дизайн, языки и способы объяснять идеи", subjects=((DisciplineAreaCode.ART_DESIGN_MEDIA, "0.6"), (DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, "0.4")), activities=((ActivityCode.CREATIVE, "0.7"), (ActivityCode.COMMUNICATION, "0.3"))),
                    _option("learning_dont_know", "Пока не знаю"),
                ),
                order=2,
                multi_select=True,
                max_selected=3,
                dimensions=("subject", "activity"),
            ),
            question(
                "core_result",
                QuestionBlock.ACTIVITIES,
                QuestionStage.WORK_STYLE,
                QuestionComponentType.SCENARIO_CHOICE,
                "Какой результат работы тебе приятнее увидеть?",
                (
                    _option("working_service", "Работающий сервис или цифровой инструмент", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),), activities=((ActivityCode.SOFTWARE_CREATION, "0.8"), (ActivityCode.COMMUNICATION, "0.2"))),
                    _option("model_data", "Модель, расчёт или найденную закономерность", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.5")), activities=((ActivityCode.DATA, "0.6"), (ActivityCode.ANALYTICAL, "0.4"))),
                    _option("tested_device", "Проверенное устройство или инженерную систему", subjects=((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.7"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.3")), activities=((ActivityCode.PHYSICAL_ENGINEERING, "0.6"), (ActivityCode.SYSTEM_DESIGN, "0.4"))),
                    _option("explained_phenomenon", "Объяснение физического явления или подтверждённую гипотезу", subjects=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.6"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.4")), activities=((ActivityCode.RESEARCH, "0.7"), (ActivityCode.ANALYTICAL, "0.3"))),
                    _option("useful_product", "Полезный продукт, понятный людям", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.3"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.3"), (DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.2"), (DisciplineAreaCode.ART_DESIGN_MEDIA, "0.2")), activities=((ActivityCode.BUSINESS, "0.4"), (ActivityCode.CREATIVE, "0.3"), (ActivityCode.COMMUNICATION, "0.3"))),
                ),
                order=3,
                dimensions=("subject", "activity"),
            ),
            question(
                "core_task_mode",
                QuestionBlock.TRADE_OFFS,
                QuestionStage.TRADE_OFFS,
                QuestionComponentType.PAIR_CHOICE,
                "Какой формат задачи тебе ближе — теория, практика или их сочетание?",
                (
                    _option("principles_model", "Сначала понять принцип, построить модель и проверить гипотезу", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.5"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.5")), activities=((ActivityCode.ANALYTICAL, "0.6"), (ActivityCode.RESEARCH, "0.4"))),
                    _option("prototype_test", "Собрать прототип и проверить его в деле", subjects=((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.5"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.2"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.3")), activities=((ActivityCode.PHYSICAL_ENGINEERING, "0.5"), (ActivityCode.SOFTWARE_CREATION, "0.3"), (ActivityCode.SYSTEM_DESIGN, "0.2"))),
                    _option("user_solution", "Решить прикладную задачу для пользователя или команды", subjects=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.3"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.3"), (DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.2"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.2")), activities=((ActivityCode.COMMUNICATION, "0.4"), (ActivityCode.BUSINESS, "0.3"), (ActivityCode.SOFTWARE_CREATION, "0.3"))),
                    _option("balanced_theory_practice", "Чередовать глубокое понимание и практическую проверку", subjects=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.25"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.25"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.25"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.25")), activities=((ActivityCode.RESEARCH, "0.25"), (ActivityCode.ANALYTICAL, "0.25"), (ActivityCode.SYSTEM_DESIGN, "0.25"), (ActivityCode.SOFTWARE_CREATION, "0.25"))),
                ),
                order=4,
                dimensions=("subject", "activity"),
            ),
            question(
                "core_anti",
                QuestionBlock.ANTI_INTERESTS,
                QuestionStage.ANTI_INTERESTS,
                QuestionComponentType.MULTI_CHOICE,
                "Что категорически не твоё? Можно выбрать до трёх пунктов.",
                (
                    _option("avoid_physics", "Физика и физические системы", anti=((DisciplineAreaCode.PHYSICS_ASTRONOMY, "1"),)),
                    _option("avoid_chemistry", "Химия и материалы", anti=((DisciplineAreaCode.CHEMISTRY_MATERIALS, "1"),)),
                    _option("avoid_programming", "Программирование и цифровые системы", anti=((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1"),)),
                    _option("avoid_math", "Большой объём математики", anti=((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1"),)),
                    _option("avoid_business", "Экономика и управление", anti=((DisciplineAreaCode.ECONOMICS_FINANCE, "0.6"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.4"))),
                    _option("avoid_people", "Коммуникации и социальные темы", anti=((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.5"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.5"))),
                    _option("no_exclusions", "Пока ничего не исключаю"),
                ),
                order=5,
                multi_select=True,
                max_selected=3,
                dimensions=("anti_interest",),
            ),
        ),
        question_set_version="proftest-v3",
    )
    _log_resolved(questionnaire)
    return questionnaire


def build_session_questionnaire() -> Questionnaire:
    """Return the default immutable questionnaire for new sessions."""

    return build_session_questionnaire_v3()


def session_questionnaire(question_set_version: str) -> Questionnaire:
    """Resolve a persisted session to its immutable questionnaire version."""

    builders = {
        "proftest-v2": build_session_questionnaire_v2,
        "proftest-v3": build_session_questionnaire_v3,
    }
    builder = builders.get(question_set_version)
    if builder is None:
        logger.warning("questionnaire_version_unknown version=%s", question_set_version[:128])
        raise ValueError(f"Unknown proftest question set: {question_set_version}")
    logger.info("questionnaire_version_selected version=%s", question_set_version)
    return builder()


def _log_resolved(questionnaire: Questionnaire) -> None:
    logger.info("questionnaire_version_published version=%s", questionnaire.question_set_version)
    logger.debug(
        "questionnaire_resolved version=%s question_count=%d option_count=%d",
        questionnaire.question_set_version,
        len(questionnaire.questions),
        sum(len(question.options) for question in questionnaire.questions),
    )


__all__ = [
    "build_questionnaire",
    "build_session_questionnaire",
    "build_session_questionnaire_v2",
    "build_session_questionnaire_v3",
    "session_questionnaire",
]
