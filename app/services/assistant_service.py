import re
from datetime import date

from app.models import Conversation, LicenseRequest, Message, Person


REQUEST_TYPE_ALIASES = {
    "medical_folder": [
        "1",
        "carpeta",
        "carpeta medica",
        "carpeta médica",
        "licencia medica",
        "licencia médica",
        "reposo medico",
        "reposo médico",
        "certificado medico",
        "certificado médico",
    ],
    "license": [
        "2",
        "lar",
        "licencia anual",
        "licencia anual reglamentaria",
        "ordinaria",
        "vacaciones",
    ],
    "other_license": [
        "3",
        "4",
        "5",
        "otra licencia",
        "otras licencias",
        "licencia especial",
        "articulo 74",
        "artículo 74",
        "razones particulares",
        "examen",
        "estudio",
        "fallecimiento",
        "duelo",
    ],
}


REQUEST_TYPE_LABELS = {
    "license": "Licencia Anual Reglamentaria",
    "medical_folder": "Carpeta Médica",
    "other_license": "Otra licencia",
}


FLOW_LABELS = {
    "medical_folder": "Carpeta Médica",
    "lar": "Licencia Anual Reglamentaria",
    "article_74": "Artículo 74",
    "exam": "Licencia por Examen / Estudio",
    "bereavement": "Licencia por Fallecimiento",
    "consultation": "Otras consultas",
}


CREATED_REQUEST_MARKERS = [
    "Ya registré tu solicitud",
    "Ya registre tu solicitud",
    "¡Registrado!",
    "Solicitud recibida",
    "Solicitud registrada",
    "Registrado.",
    "Licencia registrada",
]


NEGATIVE_OR_CORRECTION_MARKERS = [
    "no quiero licencia",
    "no es licencia",
    "no pedi licencia",
    "no pedí licencia",
    "no solicite licencia",
    "no solicité licencia",
    "me equivoque",
    "me equivoqué",
    "cambiar tramite",
    "cambiar trámite",
    "otro tramite",
    "otro trámite",
]


MENU_TEXT = (
    "¡Hola! Te damos la bienvenida al asistente virtual de Recursos Humanos.\n\n"
    "Nuestro horario de atención general: lunes a viernes de 08:00 a 16:00 hs.\n\n"
    "INFORMACIÓN IMPORTANTE:\n"
    "Si necesitás solicitar una Carpeta Médica, recordá que el aviso debe registrarse "
    "dentro de la primera hora de tu jornada laboral para que la novedad pueda ser "
    "justificada correctamente.\n\n"
    "Por favor, seleccioná una opción escribiendo el número correspondiente:\n\n"
    "1) Carpeta Médica (Enfermedad / Familiar enfermo)\n"
    "2) Licencia Anual Reglamentaria\n"
    "3) Artículo 74 (Razones particulares)\n"
    "4) Licencia por Examen / Estudio\n"
    "5) Licencia por Fallecimiento (Duelo)\n"
    "6) Otras consultas"
)


def get_assistant_block_reason(
    conversation: Conversation,
    person: Person | None,
) -> str | None:
    if conversation.assistant_paused:
        return "conversation_paused"

    if person and not person.assistant_enabled:
        return "person_assistant_disabled"

    return None


def should_assistant_reply(conversation: Conversation, person: Person | None) -> bool:
    return get_assistant_block_reason(conversation, person) is None


def save_message(db, conversation_id: int, sender_type: str, content: str) -> Message:
    message = Message(
        conversation_id=conversation_id,
        sender_type=sender_type,
        content=(content or "").strip(),
    )
    db.add(message)
    db.flush()
    return message


def normalize_text(value: str | None) -> str:
    text = (value or "").lower().strip()
    text = text.replace("á", "a")
    text = text.replace("é", "e")
    text = text.replace("í", "i")
    text = text.replace("ó", "o")
    text = text.replace("ú", "u")
    text = text.replace("ñ", "n")
    return text


def is_negative_or_correction_message(content: str | None) -> bool:
    text = normalize_text(content)

    if not text:
        return False

    return any(marker in text for marker in NEGATIVE_OR_CORRECTION_MARKERS)


def is_greeting_or_generic(content: str | None) -> bool:
    text = normalize_text(content)

    if not text:
        return True

    greetings = {
        "hola",
        "hoal",
        "buen dia",
        "buenos dias",
        "buenas",
        "buenas tardes",
        "buenas noches",
        "ok",
        "si",
        "hola buen dia",
        "hola buenas",
    }

    return text in greetings


def detect_menu_flow(content: str | None) -> str | None:
    text = normalize_text(content)

    if not text:
        return None

    compact = text.strip().replace(".", "").replace(")", "")

    if compact == "1":
        return "medical_folder"

    if compact == "2":
        return "lar"

    if compact == "3":
        return "article_74"

    if compact == "4":
        return "exam"

    if compact == "5":
        return "bereavement"

    if compact == "6":
        return "consultation"

    if "carpeta" in text or "licencia medica" in text or "licencia médica" in text:
        return "medical_folder"

    if "lar" in text or "licencia anual" in text or "vacaciones" in text:
        return "lar"

    if "articulo 74" in text or "artículo 74" in text or "razones particulares" in text:
        return "article_74"

    if "examen" in text or "estudio" in text:
        return "exam"

    if "fallecimiento" in text or "duelo" in text:
        return "bereavement"

    if "consulta" in text or "otras consultas" in text:
        return "consultation"

    return None


def request_type_from_flow(flow: str | None) -> str | None:
    if flow == "medical_folder":
        return "medical_folder"

    if flow == "lar":
        return "license"

    if flow in {"article_74", "exam", "bereavement"}:
        return "other_license"

    return None


def detect_medical_folder_for(content: str | None) -> str | None:
    text = normalize_text(content)

    if not text:
        return None

    clean = text.strip().replace(".", "").replace(")", "")

    if clean == "a":
        return "agent"

    if clean == "b":
        return "family"

    family_words = [
        "familiar",
        "familiar enfermo",
        "familia",
        "hijo",
        "hija",
        "padre",
        "madre",
        "esposo",
        "esposa",
        "conyuge",
        "cónyuge",
        "hermano",
        "hermana",
        "atencion de familiar",
        "atención de familiar",
    ]

    agent_words = [
        "afeccion propia",
        "afección propia",
        "agente",
        "por mi",
        "para mi",
        "yo",
        "titular",
        "empleado",
        "trabajador",
    ]

    if any(normalize_text(word) in text for word in family_words):
        return "family"

    if any(normalize_text(word) in text for word in agent_words):
        return "agent"

    return None


def detect_relationship(content: str | None) -> str | None:
    text = (content or "").strip()

    if not text:
        return None

    lowered = normalize_text(text)

    invalid_values = {
        "hola",
        "buen dia",
        "buenas",
        "ok",
        "si",
        "no",
        "agente",
        "familiar",
        "familiar enfermo",
        "a",
        "b",
    }

    if lowered in invalid_values:
        return None

    if extract_dni(text):
        return None

    if extract_single_date(text):
        return None

    if detect_request_type(text):
        return None

    return text


def detect_request_type(content: str | None) -> str | None:
    text = normalize_text(content)

    if not text:
        return None

    if is_negative_or_correction_message(text):
        return None

    flow = detect_menu_flow(text)

    if flow:
        return request_type_from_flow(flow)

    for request_type in ["medical_folder", "other_license", "license"]:
        aliases = REQUEST_TYPE_ALIASES[request_type]

        for alias in aliases:
            if normalize_text(alias) in text:
                return request_type

    return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None

    value = value.strip()

    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return date.fromisoformat(value)
    except ValueError:
        pass

    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value)

    if match:
        day, month, year = match.groups()

        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None

    return None


def extract_all_dates(content: str | None) -> list[date]:
    matches = re.findall(
        r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}",
        content or "",
    )

    result = []

    for value in matches:
        parsed = parse_date(value)

        if parsed:
            result.append(parsed)

    return result


def extract_dates(content: str | None) -> tuple[date | None, date | None]:
    dates = extract_all_dates(content)

    if len(dates) >= 2:
        return dates[0], dates[1]

    if len(dates) == 1:
        return dates[0], None

    return None, None


def extract_single_date(content: str | None) -> date | None:
    dates = extract_all_dates(content)

    if not dates:
        return None

    return dates[0]


def extract_dni(content: str | None) -> str | None:
    matches = re.findall(r"\b\d{7,13}\b", content or "")

    if not matches:
        return None

    return matches[0]


def extract_year(content: str | None) -> str | None:
    text = content or ""
    matches = re.findall(r"\b20\d{2}\b", text)

    if not matches:
        return None

    return matches[0]


def extract_article_74_order(content: str | None) -> str | None:
    text = normalize_text(content)

    if not text:
        return None

    if "1°" in text or "1º" in text or "1ro" in text or "primero" in text or "1" in text:
        return "1°"

    if "2°" in text or "2º" in text or "2do" in text or "segundo" in text or "2" in text:
        return "2°"

    return None


def is_real_dni(value: str | None) -> bool:
    if not value:
        return False

    clean = str(value).strip()

    return bool(re.fullmatch(r"\d{7,13}", clean))


def person_has_real_dni(person: Person | None) -> bool:
    if not person:
        return False

    return is_real_dni(person.dni)


def person_has_real_name(person: Person | None) -> bool:
    if not person:
        return False

    first_name = (person.first_name or "").strip().lower()
    last_name = (person.last_name or "").strip().lower()

    invalid_first_names = {
        "",
        "sin nombre",
        "prueba",
        "nico",
    }

    invalid_last_names = {
        "",
        "sin apellido",
    }

    if first_name in invalid_first_names:
        return False

    if last_name in invalid_last_names:
        return False

    return True


def looks_like_name(content: str | None) -> bool:
    text = (content or "").strip()

    if not text:
        return False

    if extract_dni(text):
        return False

    if extract_single_date(text):
        return False

    lowered = normalize_text(text)

    blocked_words = [
        "hola",
        "buen dia",
        "buenas",
        "licencia",
        "carpeta",
        "medica",
        "médica",
        "desde",
        "hasta",
        "motivo",
        "por ",
        "solicito",
        "quiero",
        "pido",
        "necesito",
        "pedir",
        "tramite",
        "trámite",
        "articulo",
        "artículo",
        "examen",
        "duelo",
        "fallecimiento",
    ]

    if any(word in lowered for word in blocked_words):
        return False

    parts = text.split()

    return len(parts) >= 2


def extract_name_from_message(content: str | None) -> tuple[str | None, str | None]:
    text = (content or "").strip()

    if not text:
        return None, None

    parts_by_comma = [p.strip() for p in text.split(",") if p.strip()]
    possible_name = parts_by_comma[0] if parts_by_comma else text

    if not looks_like_name(possible_name):
        return None, None

    name_parts = possible_name.split()

    if len(name_parts) == 1:
        return name_parts[0], "Sin apellido"

    if len(name_parts) >= 3:
        first_name = " ".join(name_parts[:2])
        last_name = " ".join(name_parts[2:])
    else:
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:])

    return first_name, last_name


def extract_reason(content: str | None) -> str | None:
    text = (content or "").strip()

    if not text:
        return None

    lowered = normalize_text(text)

    if lowered in ["hola", "buen dia", "buenas", "ok", "si", "no"]:
        return None

    patterns = [
        r"por\s+(.+)$",
        r"motivo\s*:\s*(.+)$",
        r"motivo\s+(.+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            reason = match.group(1).strip()

            if reason:
                return reason

    parts = [p.strip() for p in text.split(",") if p.strip()]

    if len(parts) >= 5:
        return parts[-1]

    return None


def update_person_from_message(person: Person | None, content: str | None) -> bool:
    if not person:
        return False

    changed = False

    dni = extract_dni(content)

    if dni and is_real_dni(dni):
        person.dni = dni
        changed = True

    if not person_has_real_name(person):
        first_name, last_name = extract_name_from_message(content)

        if first_name:
            person.first_name = first_name
            changed = True

        if last_name:
            person.last_name = last_name
            changed = True

    return changed


def _message_sort_key(msg: Message):
    return msg.created_at or ""


def _conversation_messages(conversation: Conversation | None) -> list[Message]:
    if not conversation:
        return []

    return sorted(conversation.messages or [], key=_message_sort_key)


def _is_created_request_message(msg: Message) -> bool:
    if msg.sender_type != "assistant":
        return False

    content = msg.content or ""

    return any(marker in content for marker in CREATED_REQUEST_MARKERS)


def _last_created_request_index(messages: list[Message]) -> int:
    start_index = 0

    for index, msg in enumerate(messages):
        if _is_created_request_message(msg):
            start_index = index + 1

    return start_index


def get_expected_field_from_prompt_text(content: str | None) -> str | None:
    text = normalize_text(content)

    if "ano del periodo" in text or "año del periodo" in text:
        return "lar_period"

    if "fecha de inicio y la fecha de finalizacion" in text:
        return "lar_dates"

    if "fecha de inicio y fecha de finalizacion" in text:
        return "lar_dates"

    if "fecha de finalizacion" in text and "fecha de inicio" in text:
        return "lar_dates"

    if "para que fecha solicitas el articulo" in text:
        return "article_74_date"

    if "fecha del examen" in text:
        return "exam_date"

    if "parentesco" in text or "parentezco" in text:
        return "bereavement_relationship"

    if "fecha de inicio de la licencia" in text:
        return "start_date"

    if "a partir de que fecha" in text:
        return "start_date"

    if "motivo de la carpeta medica" in text:
        return "medical_folder_for"

    if "envia a" in text and "envia b" in text:
        return "medical_folder_for"

    if "dni del familiar" in text:
        return "family_dni"

    if "nombre completo del familiar" in text:
        return "family_name"

    if "agente o por familiar enfermo" in text:
        return "medical_folder_for"

    if "dni" in text:
        return "dni"

    if "nombre completo" in text:
        return "name"

    if "desde que fecha" in text or "fecha desde" in text:
        return "start_date"

    if "hasta que fecha" in text:
        return "end_date"

    if "motivo" in text:
        return "reason"

    return None


def _assistant_was_asking_field_before(
    messages: list[Message],
    index: int,
) -> bool:
    for prev_index in range(index - 1, -1, -1):
        prev_msg = messages[prev_index]

        if prev_msg.sender_type == "assistant" and prev_msg.content:
            return get_expected_field_from_prompt_text(prev_msg.content) is not None

    return False


def _active_user_messages_for_current_request(
    conversation: Conversation | None,
    current_content: str | None = None,
) -> list[str]:
    messages = _conversation_messages(conversation)

    start_index = _last_created_request_index(messages)

    for index in range(start_index, len(messages)):
        msg = messages[index]

        if msg.sender_type != "user":
            continue

        if not detect_menu_flow(msg.content) and not detect_request_type(msg.content):
            continue

        if _assistant_was_asking_field_before(messages, index):
            continue

        start_index = index

    user_messages = [
        msg.content.strip()
        for msg in messages[start_index:]
        if msg.sender_type == "user" and msg.content
    ]

    if current_content:
        clean_current = current_content.strip()

        if clean_current and (not user_messages or user_messages[-1] != clean_current):
            user_messages.append(clean_current)

    return user_messages


def build_context_text(conversation: Conversation | None, current_content: str | None = None) -> str:
    parts = _active_user_messages_for_current_request(conversation, current_content)
    return "\n".join(parts)


def _get_last_assistant_message(conversation: Conversation | None) -> str:
    messages = _conversation_messages(conversation)

    for msg in reversed(messages):
        if msg.sender_type == "assistant" and msg.content:
            return msg.content

    return ""


def get_expected_field_from_last_prompt(conversation: Conversation | None) -> str | None:
    return get_expected_field_from_prompt_text(_get_last_assistant_message(conversation))


def infer_flow_from_conversation(conversation: Conversation | None) -> str | None:
    last_assistant_message = _get_last_assistant_message(conversation)

    if any(marker in (last_assistant_message or "") for marker in CREATED_REQUEST_MARKERS):
        return None

    text = normalize_text(last_assistant_message)

    if "carpeta medica" in text or "motivo de la carpeta medica" in text:
        return "medical_folder"

    if "licencia anual reglamentaria" in text or "periodo que vas a solicitar" in text:
        return "lar"

    if "articulo 74" in text:
        return "article_74"

    if "licencia por estudio" in text or "fecha del examen" in text:
        return "exam"

    if "licencia por fallecimiento" in text or "lamentamos tu perdida" in text:
        return "bereavement"

    if "otras consultas" in text:
        return "consultation"

    return None


def collect_answered_fields_from_conversation(
    conversation: Conversation | None,
) -> dict:
    result = {}

    messages = _conversation_messages(conversation)
    start_index = _last_created_request_index(messages)

    expected_field = None
    active_flow = None

    for msg in messages[start_index:]:
        if msg.sender_type == "assistant":
            expected_field = get_expected_field_from_prompt_text(msg.content)

            inferred = infer_flow_from_prompt(msg.content)

            if inferred:
                active_flow = inferred
                result["flow"] = inferred
                result["request_type"] = request_type_from_flow(inferred)

            continue

        if msg.sender_type != "user":
            continue

        content = (msg.content or "").strip()

        if not content:
            continue

        detected_flow = detect_menu_flow(content)

        if detected_flow:
            active_flow = detected_flow
            result["flow"] = detected_flow
            result["request_type"] = request_type_from_flow(detected_flow)
            expected_field = None
            continue

        if not expected_field:
            continue

        if expected_field == "lar_period":
            value = extract_year(content)

            if value:
                result["lar_period"] = value

        elif expected_field == "lar_dates":
            dates = extract_all_dates(content)

            if len(dates) >= 1:
                result["start_date"] = dates[0]

            if len(dates) >= 2:
                result["end_date"] = dates[1]

        elif expected_field == "article_74_date":
            value = extract_single_date(content)

            if value:
                result["start_date"] = value
                result["end_date"] = value

            order = extract_article_74_order(content)

            if order:
                result["article_74_order"] = order

        elif expected_field == "exam_date":
            value = extract_single_date(content)

            if value:
                result["start_date"] = value
                result["end_date"] = value

        elif expected_field == "bereavement_relationship":
            value = detect_relationship(content)

            if value:
                result["bereavement_relationship"] = value

        elif expected_field == "medical_folder_for":
            value = detect_medical_folder_for(content)

            if value:
                result["medical_folder_for"] = value
                result["request_type"] = "medical_folder"
                result["flow"] = "medical_folder"

        elif expected_field == "dni":
            value = extract_dni(content)

            if value:
                result["dni"] = value

        elif expected_field == "name":
            first_name, last_name = extract_name_from_message(content)

            if first_name:
                result["first_name"] = first_name

            if last_name:
                result["last_name"] = last_name

        elif expected_field == "start_date":
            value = extract_single_date(content)

            if value:
                result["start_date"] = value

                if active_flow in {"article_74", "exam", "bereavement"}:
                    result["end_date"] = value

        elif expected_field == "end_date":
            value = extract_single_date(content)

            if value:
                result["end_date"] = value

        elif expected_field == "reason":
            value = extract_reason(content) or content

            if value and not extract_dni(value) and not extract_single_date(value):
                result["reason"] = value

        expected_field = None

    return result


def infer_flow_from_prompt(content: str | None) -> str | None:
    text = normalize_text(content)

    if "carpeta medica" in text or "motivo de la carpeta medica" in text:
        return "medical_folder"

    if "licencia anual reglamentaria" in text or "periodo que vas a solicitar" in text:
        return "lar"

    if "articulo 74" in text:
        return "article_74"

    if "licencia por estudio" in text or "fecha del examen" in text:
        return "exam"

    if "licencia por fallecimiento" in text or "lamentamos tu perdida" in text:
        return "bereavement"

    if "otras consultas" in text:
        return "consultation"

    return None


def _extract_name_from_lines(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        first_name, last_name = extract_name_from_message(line)

        if first_name and last_name:
            return first_name, last_name

    return None, None


def build_reason_from_data(data: dict) -> str | None:
    flow = data.get("flow")

    if flow == "medical_folder":
        if data.get("medical_folder_for") == "family":
            return "Carpeta médica - atención de familiar enfermo"

        return "Carpeta médica - afección propia"

    if flow == "lar":
        period = data.get("lar_period") or "-"
        return f"Licencia Anual Reglamentaria - período {period}"

    if flow == "article_74":
        order = data.get("article_74_order") or "sin especificar"
        return f"Artículo 74 - Franquicia por razones particulares - {order}"

    if flow == "exam":
        return "Licencia por Examen / Estudio"

    if flow == "bereavement":
        relationship = data.get("bereavement_relationship") or "-"
        return f"Licencia por fallecimiento - parentesco: {relationship}"

    return data.get("reason")


def infer_request_type_from_conversation(conversation: Conversation | None) -> str | None:
    flow = infer_flow_from_conversation(conversation)

    if flow:
        return request_type_from_flow(flow)

    return None


def conversation_has_active_request_flow(conversation: Conversation | None) -> bool:
    messages = _conversation_messages(conversation)
    start_index = _last_created_request_index(messages)

    for msg in messages[start_index:]:
        if msg.sender_type == "user" and detect_menu_flow(msg.content):
            return True

        if msg.sender_type == "user" and detect_request_type(msg.content):
            return True

        if msg.sender_type == "assistant":
            expected = get_expected_field_from_prompt_text(msg.content)

            if expected in {
                "dni",
                "name",
                "medical_folder_for",
                "family_dni",
                "family_name",
                "family_relationship",
                "start_date",
                "end_date",
                "reason",
                "lar_period",
                "lar_dates",
                "article_74_date",
                "exam_date",
                "bereavement_relationship",
            }:
                return True

    return False


def collect_request_data(
    person: Person | None,
    content: str | None,
    context_text: str | None = None,
    conversation: Conversation | None = None,
) -> dict:
    active_text = context_text or content or ""
    lines = [line.strip() for line in active_text.splitlines() if line.strip()]

    answered_fields = collect_answered_fields_from_conversation(conversation)

    flow = detect_menu_flow(active_text)

    if not flow:
        flow = answered_fields.get("flow")

    if not flow:
        flow = infer_flow_from_conversation(conversation)

    request_type = request_type_from_flow(flow)

    if not request_type:
        request_type = detect_request_type(active_text)

    if not request_type:
        request_type = answered_fields.get("request_type")

    dates = extract_all_dates(active_text)
    start_date = dates[0] if len(dates) >= 1 else None
    end_date = dates[1] if len(dates) >= 2 else None

    if not start_date:
        start_date = answered_fields.get("start_date")

    if not end_date:
        end_date = answered_fields.get("end_date")

    if flow in {"article_74", "exam", "bereavement"} and start_date and not end_date:
        end_date = start_date

    if request_type == "medical_folder":
        end_date = None

    dni = extract_dni(active_text)

    first_name, last_name = _extract_name_from_lines(lines)

    lar_period = extract_year(active_text) or answered_fields.get("lar_period")
    article_74_order = extract_article_74_order(active_text) or answered_fields.get("article_74_order")
    bereavement_relationship = answered_fields.get("bereavement_relationship")

    if flow == "bereavement" and not bereavement_relationship:
        expected = get_expected_field_from_last_prompt(conversation)

        if expected == "bereavement_relationship" and lines:
            bereavement_relationship = detect_relationship(lines[-1])

    medical_folder_for = None
    family_member_dni = None
    family_member_full_name = None
    family_relationship = None

    if request_type == "medical_folder":
        medical_folder_for = detect_medical_folder_for(active_text)

        if not medical_folder_for:
            medical_folder_for = answered_fields.get("medical_folder_for")

    reason = build_reason_from_data(
        {
            "flow": flow,
            "medical_folder_for": medical_folder_for,
            "lar_period": lar_period,
            "article_74_order": article_74_order,
            "bereavement_relationship": bereavement_relationship,
        }
    )

    if not reason:
        reason = answered_fields.get("reason")

    if person:
        if not dni and person_has_real_dni(person):
            dni = person.dni

        if person_has_real_name(person):
            if not first_name:
                first_name = person.first_name

            if not last_name:
                last_name = person.last_name

    return {
        "flow": flow,
        "request_type": request_type,
        "start_date": start_date,
        "end_date": end_date,
        "dni": dni,
        "first_name": first_name,
        "last_name": last_name,
        "reason": reason,
        "medical_folder_for": medical_folder_for,
        "family_member_dni": family_member_dni,
        "family_member_full_name": family_member_full_name,
        "family_relationship": family_relationship,
        "lar_period": lar_period,
        "article_74_order": article_74_order,
        "bereavement_relationship": bereavement_relationship,
    }


def get_missing_field(data: dict) -> str | None:
    if data.get("flow") == "consultation":
        return None

    if not data.get("request_type"):
        return "request_type"

    if not data.get("dni"):
        return "dni"

    if not data.get("first_name") or not data.get("last_name"):
        return "name"

    flow = data.get("flow")

    if flow == "medical_folder":
        if not data.get("start_date"):
            return "start_date"

        if not data.get("medical_folder_for"):
            return "medical_folder_for"

        return None

    if flow == "lar":
        if not data.get("lar_period"):
            return "lar_period"

        if not data.get("start_date") or not data.get("end_date"):
            return "lar_dates"

        return None

    if flow == "article_74":
        if not data.get("start_date"):
            return "article_74_date"

        if not data.get("article_74_order"):
            return "article_74_date"

        return None

    if flow == "exam":
        if not data.get("start_date"):
            return "exam_date"

        return None

    if flow == "bereavement":
        if not data.get("bereavement_relationship"):
            return "bereavement_relationship"

        if not data.get("start_date"):
            return "start_date"

        return None

    if not data.get("start_date"):
        return "start_date"

    if data.get("request_type") != "medical_folder" and not data.get("end_date"):
        return "end_date"

    if not data.get("reason"):
        return "reason"

    return None


def build_missing_field_reply(missing_field: str, data: dict | None = None) -> str:
    data = data or {}
    flow = data.get("flow")

    if missing_field == "request_type":
        return MENU_TEXT

    if missing_field == "dni":
        return "Para avanzar necesito tu DNI. Enviámelo solo con números, por ejemplo: 30111222."

    if missing_field == "name":
        return "Ahora necesito tu nombre completo. Ejemplo: Juan Pérez."

    if missing_field == "lar_period":
        return (
            "Elegiste Licencia Anual Reglamentaria. Para iniciar el pedido, "
            "indicame el año del período que vas a solicitar. Por ejemplo: 2025."
        )

    if missing_field == "lar_dates":
        return (
            "Perfecto. Ahora indicame la fecha de inicio y la fecha de finalización "
            "del tramo que vas a usar, junto con los días hábiles correspondientes. "
            "Ejemplo: Desde 01/06/2026 hasta 10/06/2026."
        )

    if missing_field == "article_74_date":
        return (
            "Seleccionaste Artículo 74, franquicia por razones particulares. "
            "Recordá que este beneficio cuenta con un límite anual según el régimen vigente. "
            "¿Para qué fecha solicitás el artículo? Indicá la fecha en formato DD/MM/AAAA "
            "y si corresponde a 1° o 2°."
        )

    if missing_field == "exam_date":
        return (
            "Elegiste Licencia por Estudio. ¿Cuál es la fecha del examen? "
            "Escribila en formato DD/MM/AAAA."
        )

    if missing_field == "bereavement_relationship":
        return (
            "Lamentamos tu pérdida. Para registrar la licencia por fallecimiento, "
            "por favor indicame el parentesco. Ejemplo: cónyuge, hijo, padre/madre, "
            "hermano, etc. Esto permite determinar los días que corresponden según "
            "el régimen de licencias vigente."
        )

    if missing_field == "medical_folder_for":
        return (
            "Gracias. Seleccioná el motivo de la carpeta médica:\n\n"
            "A) Afección propia\n"
            "B) Atención de familiar enfermo"
        )

    if missing_field == "start_date":
        if flow == "medical_folder":
            return (
                "Elegiste Carpeta Médica. ¿A partir de qué fecha la solicitás? "
                "Escribí en formato DD/MM/AAAA. Por ejemplo: 20/05/2026."
            )

        if flow == "bereavement":
            return "Gracias. Indicame la fecha de inicio de la licencia en formato DD/MM/AAAA."

        return "¿Desde qué fecha solicitás la licencia? Podés escribirla como 10/05/2026."

    if missing_field == "end_date":
        if data.get("start_date"):
            return (
                f"Perfecto. Tengo como fecha desde {data['start_date'].strftime('%d/%m/%Y')}. "
                "¿Hasta qué fecha solicitás la licencia?"
            )

        return "¿Hasta qué fecha solicitás la licencia? Podés escribirla como 12/05/2026."

    if missing_field == "reason":
        return "¿Cuál es el motivo de la solicitud?"

    return MENU_TEXT


def build_assistant_reply(content: str) -> str:
    flow = detect_menu_flow(content)

    if flow == "medical_folder":
        return (
            "Elegiste Carpeta Médica. ¿A partir de qué fecha la solicitás? "
            "Escribí en formato DD/MM/AAAA. Por ejemplo: 20/05/2026."
        )

    if flow == "lar":
        return (
            "Elegiste Licencia Anual Reglamentaria. Para iniciar el pedido, "
            "indicame el año del período que vas a solicitar. Por ejemplo: 2025."
        )

    if flow == "article_74":
        return (
            "Seleccionaste Artículo 74, franquicia por razones particulares. "
            "Recordá que este beneficio cuenta con un límite anual según el régimen vigente. "
            "¿Para qué fecha solicitás el artículo? Indicá la fecha en formato DD/MM/AAAA "
            "y si corresponde a 1° o 2°."
        )

    if flow == "exam":
        return (
            "Elegiste Licencia por Estudio. ¿Cuál es la fecha del examen? "
            "Escribila en formato DD/MM/AAAA."
        )

    if flow == "bereavement":
        return (
            "Lamentamos tu pérdida. Para registrar la licencia por fallecimiento, "
            "por favor indicame el parentesco. Ejemplo: cónyuge, hijo, padre/madre, "
            "hermano, etc. Esto permite determinar los días que corresponden según "
            "el régimen de licencias vigente."
        )

    if flow == "consultation":
        return (
            "Seleccionaste Otras consultas. Por favor escribí tu consulta y el equipo "
            "de RRHH la revisará a la brevedad."
        )

    return MENU_TEXT


def try_create_license_request_from_message(
    db,
    person: Person | None,
    content: str,
    context_text: str | None = None,
    conversation: Conversation | None = None,
) -> LicenseRequest | None:
    if not person:
        return None

    if is_negative_or_correction_message(content):
        return None

    flow = detect_menu_flow(content) or infer_flow_from_conversation(conversation)

    if flow == "consultation":
        return None

    if not detect_request_type(content) and not conversation_has_active_request_flow(conversation):
        return None

    data = collect_request_data(
        person=person,
        content=content,
        context_text=context_text,
        conversation=conversation,
    )

    if data.get("flow") == "consultation":
        return None

    missing_field = get_missing_field(data)

    if missing_field:
        return None

    person.dni = data["dni"]

    if not person_has_real_name(person):
        person.first_name = data["first_name"]
        person.last_name = data["last_name"]

    end_date = data.get("end_date")

    if data.get("request_type") == "medical_folder":
        end_date = None

    item = LicenseRequest(
        person_id=person.id,
        request_type=data["request_type"],
        status="pending",
        start_date=data["start_date"],
        end_date=end_date,
        reason=data["reason"],
        admin_notes="Solicitud creada automáticamente desde conversación de WhatsApp.",
        medical_folder_for=data.get("medical_folder_for"),
        family_member_dni=data.get("family_member_dni"),
        family_member_full_name=data.get("family_member_full_name"),
        family_relationship=data.get("family_relationship"),
    )

    db.add(item)
    db.flush()

    return item


def build_created_request_reply(item: LicenseRequest) -> str:
    if item.request_type == "medical_folder":
        return (
            f"¡Registrado! Tu solicitud de Carpeta Médica del día "
            f"{item.start_date.strftime('%d/%m/%Y')} quedó asentada bajo revisión administrativa.\n\n"
            "📢 Paso siguiente: Recordá que debés gestionar la justificación ante Más Salud "
            "/ Reconocimiento Médico con tu certificado médico en el día de la fecha. "
            "Al obtener el comprobante emitido por certificado médico auditado, adjuntalo "
            "a este mismo mensaje para su carga en el sistema."
        )

    reason = normalize_text(item.reason)

    if "licencia anual reglamentaria" in reason:
        return (
            "Solicitud recibida. Recordá que las vacaciones están sujetas a las necesidades "
            "de servicio y requieren autorización previa de tu jefe directo. Pasamos la novedad "
            "al área de licencias para verificar tus días disponibles. En breve adjuntamos tu formulario."
        )

    if "articulo 74" in reason:
        return (
            f"Solicitud registrada para el día {item.start_date.strftime('%d/%m/%Y')}. "
            "Recordá que el otorgamiento definitivo queda supeditado a la autorización de la "
            "jefatura de tu área mediante la firma de la planilla correspondiente. "
            "En breve adjuntamos tu formulario."
        )

    if "examen" in reason or "estudio" in reason:
        return (
            "Registrado. Tené en cuenta que, al reintegrarte a tus funciones, es obligatorio "
            "presentar ante el área de Personal el certificado de examen correspondiente emitido "
            "por la institución educativa para evitar el descuento de los días. "
            "¡Éxitos en tu examen! En breve adjuntamos tu formulario."
        )

    if "fallecimiento" in reason or "duelo" in reason:
        return (
            "Licencia registrada. Te acompañamos en este momento. Al regresar a tu puesto, "
            "por favor acercá al área de RRHH la fotocopia del acta de defunción y la documentación "
            "que acredite el vínculo para proceder a la justificación definitiva."
        )

    request_type = REQUEST_TYPE_LABELS.get(item.request_type, item.request_type)

    return (
        f"Ya registré tu solicitud de {request_type} "
        f"desde {item.start_date} hasta {item.end_date}. "
        f"Quedó pendiente de revisión administrativa."
    )


def build_conversational_reply(
    person: Person | None,
    conversation: Conversation | None,
    content: str,
) -> str:
    if is_negative_or_correction_message(content):
        return (
            "Entendido. Volvamos al menú principal.\n\n"
            f"{MENU_TEXT}"
        )

    flow = detect_menu_flow(content)

    if flow == "consultation":
        return (
            "Seleccionaste Otras consultas. Por favor escribí tu consulta y el equipo "
            "de RRHH la revisará a la brevedad."
        )

    if flow and not conversation_has_active_request_flow(conversation):
        return build_assistant_reply(content)

    if not detect_request_type(content) and not conversation_has_active_request_flow(conversation):
        return MENU_TEXT

    context_text = build_context_text(conversation, content)

    data = collect_request_data(
        person=person,
        content=content,
        context_text=context_text,
        conversation=conversation,
    )

    if data.get("flow") == "consultation":
        return (
            "Por favor escribí tu consulta y el equipo de RRHH la revisará a la brevedad."
        )

    missing_field = get_missing_field(data)

    if missing_field:
        return build_missing_field_reply(missing_field, data)

    return "Ya tengo los datos necesarios. Estoy registrando tu solicitud para revisión de RRHH."


def build_missing_identity_reply() -> str:
    return (
        "Para avanzar necesito tus datos personales. "
        "Enviame tu DNI solo con números, por ejemplo: 30111222."
    )


def should_request_identity_before_creating(
    person: Person | None,
    content: str,
    context_text: str | None = None,
) -> bool:
    data = collect_request_data(
        person=person,
        content=content,
        context_text=context_text,
    )

    missing_field = get_missing_field(data)

    return missing_field is not None