import re
from datetime import date

from app.models import Conversation, LicenseRequest, Message, Person


REQUEST_TYPE_ALIASES = {
    "medical_folder": [
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
    "other_license": [
        "otra licencia",
        "otras licencias",
        "licencia especial",
        "licencia por examen",
        "examen",
    ],
    "license": [
        "licencia",
        "licencias",
        "lar",
        "licencia anual",
        "licencia anual reglamentaria",
        "ordinaria",
        "vacaciones",
    ],
}


REQUEST_TYPE_LABELS = {
    "license": "licencia",
    "medical_folder": "carpeta médica",
    "other_license": "otra licencia",
}


CREATED_REQUEST_MARKERS = [
    "Ya registré tu solicitud",
    "Ya registre tu solicitud",
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


def detect_medical_folder_for(content: str | None) -> str | None:
    text = normalize_text(content)

    if not text:
        return None

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
    ]

    agent_words = [
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

    # Si el usuario está corrigiendo o negando una licencia,
    # no tomamos la palabra "licencia" como nuevo trámite.
    if is_negative_or_correction_message(text):
        return None

    # Importante: carpeta médica primero.
    # Si se evalúa licencia antes, puede confundir "licencia médica" con licencia común.
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
    matches = re.findall(r"\b\d{7,8}\b", content or "")

    if not matches:
        return None

    return matches[0]


def is_real_dni(value: str | None) -> bool:
    if not value:
        return False

    return bool(re.fullmatch(r"\d{7,8}", str(value).strip()))


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

    # Si viene todo junto separado por comas:
    # Solicito licencia, Nombre Apellido, DNI, fecha - fecha, motivo
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

    # El nombre solo se toma automáticamente si todavía no hay nombre real cargado.
    # Una vez cargado, mensajes posteriores no pueden modificarlo.
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


def _is_new_request_user_message(msg: Message) -> bool:
    if msg.sender_type != "user":
        return False

    return detect_request_type(msg.content) is not None


def _last_created_request_index(messages: list[Message]) -> int:
    start_index = 0

    for index, msg in enumerate(messages):
        if _is_created_request_message(msg):
            start_index = index + 1

    return start_index


def get_expected_field_from_prompt_text(content: str | None) -> str | None:
    text = normalize_text(content)

    if "dni del familiar" in text:
        return "family_dni"

    if "nombre completo del familiar" in text:
        return "family_name"

    if "parentesco" in text or "parentezco" in text:
        return "family_relationship"

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

    # Dentro del tramo activo, si aparece un nuevo trámite real que no es
    # respuesta a una pregunta del asistente, empezamos el contexto ahí.
    for index in range(start_index, len(messages)):
        msg = messages[index]

        if msg.sender_type != "user":
            continue

        if not detect_request_type(msg.content):
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


def collect_answered_fields_from_conversation(
    conversation: Conversation | None,
) -> dict:
    """
    Reconstruye datos ya respondidos mirando la secuencia:
    asistente pregunta -> usuario responde.

    Importante:
    Solo reconstruye desde la última solicitud registrada.
    Si ya se creó una solicitud y luego el usuario dice "hola",
    NO debe reutilizar los datos viejos para crear otra solicitud.
    """
    result = {}

    messages = _conversation_messages(conversation)
    start_index = _last_created_request_index(messages)

    expected_field = None

    for msg in messages[start_index:]:
        if msg.sender_type == "assistant":
            expected_field = get_expected_field_from_prompt_text(msg.content)
            continue

        if msg.sender_type != "user":
            continue

        content = (msg.content or "").strip()

        if not content or not expected_field:
            continue

        if expected_field == "medical_folder_for":
            value = detect_medical_folder_for(content)

            if value:
                result["medical_folder_for"] = value
                result["request_type"] = "medical_folder"

        elif expected_field == "family_dni":
            value = extract_dni(content)

            if value:
                result["family_member_dni"] = value

        elif expected_field == "family_name":
            candidate = content.strip()

            if (
                candidate
                and not extract_dni(candidate)
                and not extract_single_date(candidate)
                and not detect_request_type(candidate)
                and not detect_medical_folder_for(candidate)
                and len(candidate.split()) >= 2
            ):
                result["family_member_full_name"] = candidate

        elif expected_field == "family_relationship":
            value = detect_relationship(content)

            if value:
                result["family_relationship"] = value

        elif expected_field == "start_date":
            value = extract_single_date(content)

            if value:
                result["start_date"] = value

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


def _extract_name_from_lines(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        first_name, last_name = extract_name_from_message(line)

        if first_name and last_name:
            return first_name, last_name

    return None, None


def _extract_reason_from_lines(lines: list[str], conversation: Conversation | None) -> str | None:
    expected = get_expected_field_from_last_prompt(conversation)

    # Primero intentamos motivos explícitos tipo:
    # "por reposo", "motivo: artículo 74", "motivo licencia anual"
    for line in reversed(lines):
        reason = extract_reason(line)

        if reason:
            return reason

    # Si el asistente preguntó motivo, el próximo mensaje del usuario
    # se toma como motivo aunque diga "LAR", "Licencia", "Artículo 74", etc.
    if expected == "reason" and lines:
        candidate = lines[-1].strip()

        if not candidate:
            return None

        lowered = normalize_text(candidate)

        invalid_values = {
            "hola",
            "buen dia",
            "buenas",
            "ok",
            "si",
            "no",
        }

        if lowered in invalid_values:
            return None

        if extract_dni(candidate):
            return None

        if extract_single_date(candidate):
            return None

        return candidate

    return None


def _extract_medical_folder_for_from_lines(
    lines: list[str],
    conversation: Conversation | None,
) -> str | None:
    expected = get_expected_field_from_last_prompt(conversation)

    for line in lines:
        detected = detect_medical_folder_for(line)

        if detected:
            return detected

    if expected == "medical_folder_for" and lines:
        return detect_medical_folder_for(lines[-1])

    return None


def _extract_family_dni_from_lines(
    lines: list[str],
    conversation: Conversation | None,
) -> str | None:
    expected = get_expected_field_from_last_prompt(conversation)

    if expected == "family_dni" and lines:
        return extract_dni(lines[-1])

    # Si vienen todos los DNI en el contexto, el primero suele ser del agente
    # y el segundo puede ser del familiar.
    all_dnis: list[str] = []

    for line in lines:
        dni = extract_dni(line)

        if dni:
            all_dnis.append(dni)

    if len(all_dnis) >= 2:
        return all_dnis[-1]

    return None


def _extract_family_name_from_lines(
    lines: list[str],
    conversation: Conversation | None,
) -> str | None:
    expected = get_expected_field_from_last_prompt(conversation)

    if expected == "family_name" and lines:
        candidate = lines[-1].strip()

        if extract_dni(candidate):
            return None

        if extract_single_date(candidate):
            return None

        if detect_request_type(candidate):
            return None

        if detect_medical_folder_for(candidate):
            return None

        if len(candidate.split()) >= 2:
            return candidate

    return None


def _extract_family_relationship_from_lines(
    lines: list[str],
    conversation: Conversation | None,
) -> str | None:
    expected = get_expected_field_from_last_prompt(conversation)

    if expected == "family_relationship" and lines:
        return detect_relationship(lines[-1])

    return None


def infer_request_type_from_conversation(conversation: Conversation | None) -> str | None:
    """
    Mantiene el tipo de trámite cuando el usuario responde una pregunta corta
    como "agente", "familiar", una fecha o un motivo.

    Pero NO debe inferir desde un mensaje final tipo:
    "Ya registré tu solicitud..."
    porque eso provocaría duplicados cuando el usuario luego dice "hola".
    """
    last_assistant_message = _get_last_assistant_message(conversation)

    if any(marker in (last_assistant_message or "") for marker in CREATED_REQUEST_MARKERS):
        return None

    text = normalize_text(last_assistant_message)

    if (
        "carpeta medica" in text
        or "familiar enfermo" in text
        or "dni del familiar" in text
        or "nombre completo del familiar" in text
        or "parentesco" in text
        or "parentezco" in text
    ):
        return "medical_folder"

    if "otra licencia" in text:
        return "other_license"

    if "licencia" in text:
        return "license"

    return None


def conversation_has_active_request_flow(conversation: Conversation | None) -> bool:
    """
    Devuelve True si después de la última solicitud registrada
    hay un flujo activo de carga de solicitud.

    Sirve para evitar que un "hola" posterior a una solicitud ya creada
    vuelva a registrar la misma solicitud con datos viejos.
    """
    messages = _conversation_messages(conversation)
    start_index = _last_created_request_index(messages)

    for msg in messages[start_index:]:
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

    request_type = detect_request_type(active_text)

    if not request_type:
        request_type = answered_fields.get("request_type")

    if not request_type:
        request_type = infer_request_type_from_conversation(conversation)

    dates = extract_all_dates(active_text)
    start_date = dates[0] if len(dates) >= 1 else None
    end_date = dates[1] if len(dates) >= 2 else None

    if not start_date:
        start_date = answered_fields.get("start_date")

    if not end_date:
        end_date = answered_fields.get("end_date")

    # Carpeta médica no usa fecha hasta en la carga inicial.
    # Aunque el usuario escriba dos fechas, se conserva solo fecha desde.
    if request_type == "medical_folder":
        end_date = None

    dni = extract_dni(active_text)

    first_name, last_name = _extract_name_from_lines(lines)

    reason = _extract_reason_from_lines(lines, conversation)

    if not reason:
        reason = answered_fields.get("reason")

    medical_folder_for = None
    family_member_dni = None
    family_member_full_name = None
    family_relationship = None

    if request_type == "medical_folder":
        medical_folder_for = _extract_medical_folder_for_from_lines(lines, conversation)

        if not medical_folder_for:
            medical_folder_for = answered_fields.get("medical_folder_for")

        if medical_folder_for == "family":
            family_member_dni = _extract_family_dni_from_lines(lines, conversation)

            if not family_member_dni:
                family_member_dni = answered_fields.get("family_member_dni")

            family_member_full_name = _extract_family_name_from_lines(lines, conversation)

            if not family_member_full_name:
                family_member_full_name = answered_fields.get("family_member_full_name")

            family_relationship = _extract_family_relationship_from_lines(lines, conversation)

            if not family_relationship:
                family_relationship = answered_fields.get("family_relationship")

    # Si la persona ya tiene datos reales, los usamos para no pedirlos de nuevo.
    # Pero NO los modificamos por mensajes posteriores.
    if person:
        if not dni and person_has_real_dni(person):
            dni = person.dni

        if person_has_real_name(person):
            if not first_name:
                first_name = person.first_name

            if not last_name:
                last_name = person.last_name

    return {
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
    }


def get_missing_field(data: dict) -> str | None:
    if not data.get("request_type"):
        return "request_type"

    if not data.get("dni"):
        return "dni"

    if not data.get("first_name") or not data.get("last_name"):
        return "name"

    # Carpeta médica: primero definir si es por agente o familiar enfermo.
    if data.get("request_type") == "medical_folder":
        if not data.get("medical_folder_for"):
            return "medical_folder_for"

        if data.get("medical_folder_for") == "family":
            if not data.get("family_member_dni"):
                return "family_dni"

            if not data.get("family_member_full_name"):
                return "family_name"

            if not data.get("family_relationship"):
                return "family_relationship"

    if not data.get("start_date"):
        return "start_date"

    # Licencias y otras licencias sí piden fecha hasta.
    # Carpeta médica NO pide fecha hasta; queda NULL hasta cierre administrativo.
    if data.get("request_type") != "medical_folder" and not data.get("end_date"):
        return "end_date"

    if not data.get("reason"):
        return "reason"

    return None


def build_missing_field_reply(missing_field: str, data: dict | None = None) -> str:
    data = data or {}

    if missing_field == "request_type":
        return (
            "Hola. Puedo ayudarte con pedidos de licencias, carpeta médica u otras licencias. "
            "Indicame qué trámite necesitás realizar."
        )

    if missing_field == "dni":
        return "Para avanzar necesito tu DNI. Enviámelo solo con números, por ejemplo: 30111222."

    if missing_field == "name":
        return "Ahora necesito tu nombre completo. Ejemplo: Juan Pérez."

    if missing_field == "medical_folder_for":
        return (
            "La carpeta médica, ¿es por el agente o por familiar enfermo? "
            "Respondé: Agente o Familiar enfermo."
        )

    if missing_field == "family_dni":
        return "Indicame el DNI del familiar enfermo, solo con números."

    if missing_field == "family_name":
        return "Indicame el nombre completo del familiar enfermo."

    if missing_field == "family_relationship":
        return "Indicame el parentesco con el familiar enfermo. Ejemplo: madre, padre, hijo, cónyuge."

    if missing_field == "start_date":
        if data.get("request_type") == "medical_folder":
            return "¿Desde qué fecha solicitás la carpeta médica? Podés escribirla como 10/05/2026."

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

    return (
        "Para registrar la solicitud necesito tipo de licencia, DNI, nombre completo, "
        "fecha desde, fecha hasta y motivo. Para carpeta médica solo se pide fecha desde."
    )


def build_assistant_reply(content: str) -> str:
    request_type = detect_request_type(content)

    if request_type == "medical_folder":
        return (
            "Para iniciar una carpeta médica necesito estos datos: "
            "DNI, nombre completo, si es por agente o familiar enfermo, fecha desde y motivo."
        )

    if request_type == "license":
        return (
            "Para solicitar una licencia necesito estos datos: "
            "DNI, nombre completo, fecha desde, fecha hasta y motivo."
        )

    if request_type == "other_license":
        return (
            "Para solicitar otra licencia necesito estos datos: "
            "DNI, nombre completo, tipo de licencia, fecha desde, fecha hasta y motivo."
        )

    return (
        "Hola. Puedo ayudarte con pedidos de licencias, carpeta médica u otras licencias. "
        "Indicame qué trámite necesitás realizar."
    )


def try_create_license_request_from_message(
    db,
    person: Person | None,
    content: str,
    context_text: str | None = None,
    conversation: Conversation | None = None,
) -> LicenseRequest | None:
    if not person:
        return None

    # Si no hay un trámite activo, no intentamos crear nada.
    # Evita duplicar solicitudes cuando el usuario dice "hola" después de una solicitud ya registrada.
    if is_negative_or_correction_message(content):
        return None

    if not detect_request_type(content) and not conversation_has_active_request_flow(conversation):
        return None

    data = collect_request_data(
        person=person,
        content=content,
        context_text=context_text,
        conversation=conversation,
    )

    missing_field = get_missing_field(data)

    if missing_field:
        return None

    person.dni = data["dni"]

    # El nombre solo se carga si todavía no tiene nombre real.
    if not person_has_real_name(person):
        person.first_name = data["first_name"]
        person.last_name = data["last_name"]

    # Para carpeta médica, end_date queda NULL hasta que RRHH la complete.
    # Para licencias y otras licencias se conserva la fecha hasta.
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
    request_type = REQUEST_TYPE_LABELS.get(item.request_type, item.request_type)

    if item.request_type == "medical_folder":
        if item.medical_folder_for == "family":
            return (
                f"Ya registré tu solicitud de {request_type} por familiar enfermo "
                f"desde {item.start_date}. "
                f"Familiar: {item.family_member_full_name or '-'}, "
                f"DNI: {item.family_member_dni or '-'}, "
                f"Parentesco: {item.family_relationship or '-'}. "
                f"Quedó pendiente de revisión administrativa."
            )

        return (
            f"Ya registré tu solicitud de {request_type} por el agente "
            f"desde {item.start_date}. "
            f"Quedó pendiente de revisión administrativa."
        )

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
            "Entendido. Indicame qué trámite necesitás realizar: "
            "licencia, carpeta médica u otra licencia."
        )

    # Si el usuario solo saluda después de una solicitud ya registrada,
    # no seguimos con el trámite viejo ni volvemos a registrar nada.
    if not detect_request_type(content) and not conversation_has_active_request_flow(conversation):
        return (
            "Hola. Puedo ayudarte con pedidos de licencias, carpeta médica u otras licencias. "
            "Indicame qué trámite necesitás realizar."
        )

    context_text = build_context_text(conversation, content)

    data = collect_request_data(
        person=person,
        content=content,
        context_text=context_text,
        conversation=conversation,
    )

    missing_field = get_missing_field(data)

    if missing_field:
        return build_missing_field_reply(missing_field, data)

    return (
        "Ya tengo los datos necesarios. Estoy registrando tu solicitud para revisión de RRHH."
    )


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