# Manual de Usuario - Sistema RRHH Licencias

## 1. Introducción
El sistema **RRHH Licencias** es una plataforma integral diseñada para la gestión de solicitudes de licencias, carpetas médicas y otras ausencias del personal. El sistema se destaca por integrar un **asistente virtual (bot) de WhatsApp** que automatiza la recepción de pedidos, permitiendo al personal de RRHH y operadores gestionar las solicitudes de manera eficiente desde un panel centralizado.

---

## 2. Acceso al Sistema
Para acceder al panel administrativo:
1. Ingrese a la URL proporcionada por el administrador.
2. Inicie sesión con su correo electrónico y contraseña.
3. Al finalizar su turno, recuerde cerrar sesión por seguridad.

---

## 3. Roles y Permisos
El sistema cuenta con tres niveles de acceso:

*   **ADMIN (Administrador):** Acceso total al sistema. Puede gestionar usuarios, ver registros de auditoría, administrar personas y todas las solicitudes de licencias.
*   **RRHH (Recursos Humanos):** Enfocado en la gestión operativa. Puede administrar personas, crear y editar solicitudes de licencias y cambiar sus estados. No tiene acceso a la gestión de usuarios ni auditoría detallada.
*   **OPERADOR:** Orientado a la atención al cliente/empleado. Su función principal es gestionar el panel de mensajes y responder consultas vía WhatsApp. No puede cambiar estados de licencias ni gestionar usuarios.

---

## 4. Dashboard (Panel Principal)
Al ingresar, los perfiles ADMIN y RRHH verán un resumen estadístico que incluye:
*   Total de personas registradas.
*   Total de solicitudes procesadas.
*   Desglose por tipo (Licencias, Carpeta Médica, Otras).
*   Cantidad de solicitudes pendientes de revisión.
*   Listado de las últimas solicitudes recibidas con acceso directo al detalle.

---

## 5. Gestión de Licencias y Trámites
El sistema permite gestionar tres tipos principales de trámites:
1.  **Licencias (LAR/Vacaciones):** Requiere fecha de inicio y fin.
2.  **Carpeta Médica:** Se registra la fecha de inicio. La fecha de fin queda abierta hasta que sea completada por el área administrativa. Puede ser por el "Agente" o por "Familiar Enfermo".
3.  **Otras Licencias:** Trámites especiales (examen, días por fallecimiento, etc.).

### Funcionalidades:
*   **Listado General:** Filtre por tipo, estado o realice búsquedas por DNI o nombre.
*   **Exportación:** Descargue los listados filtrados en formato CSV para trabajar en Excel.
*   **Creación Manual:** Permite registrar un trámite recibido por medios externos (papel o teléfono).
*   **Cambio de Estado:** Las solicitudes pasan por diferentes estados: *Pendiente, Aprobada, Rechazada, Observada, Cancelada*.
*   **Notificaciones Automáticas:** Al cambiar el estado de una solicitud, el sistema envía automáticamente un mensaje de WhatsApp al empleado informando la novedad.

---

## 6. Panel de Mensajes y Asistente Virtual
Este panel permite interactuar en tiempo real con los empleados a través de WhatsApp.

*   **Asistente Virtual (Bot):** Por defecto, un bot guía al usuario para recolectar los datos del trámite.
*   **Pausar Asistente:** Si un operador desea intervenir, puede pausar el bot para que no interfiera en la conversación humana.
*   **Respuesta Humana:** Al escribir y enviar un mensaje desde el panel, el sistema pausa automáticamente al asistente y envía el texto al WhatsApp del empleado.
*   **Reanudar Asistente:** Una vez finalizada la intervención humana, se puede reactivar el bot para futuros trámites.
*   **Historial:** Se mantiene un registro completo de los mensajes enviados por el usuario, el asistente y los operadores.

---

## 7. Gestión de Personas (Empleados)
Base de datos de todos los empleados que han interactuado con el sistema.
*   **Datos:** DNI, Nombre, Teléfono, Correo, Área y Número de Legajo.
*   **Control del Asistente:** Es posible desactivar el asistente virtual para una persona específica si se prefiere una atención siempre humana.

---

## 8. Gestión de Usuarios (Solo ADMIN)
Permite administrar quiénes acceden al panel administrativo.
*   Creación de nuevos usuarios (ADMIN, RRHH, OPERADOR).
*   Activación/Desactivación de cuentas.
*   Restablecimiento de contraseñas.

---

## 9. Auditoría (Solo ADMIN)
Registro detallado de todas las acciones críticas realizadas en el sistema para garantizar la transparencia y seguridad.
*   **Acciones registradas:** Inicios de sesión, cambios de estado en licencias, edición de datos de personas, envíos de mensajes, etc.
*   **Detalle:** Permite ver exactamente qué valor cambió (valor anterior vs. valor nuevo).
*   **Exportación:** Los registros de auditoría también pueden exportarse a CSV.

---

## 10. Flujo del Bot de WhatsApp (Guía para el Empleado)
Cuando un empleado escribe al WhatsApp:
1.  **Saludo e Intención:** El bot identifica si el usuario desea una licencia o carpeta médica.
2.  **Identificación:** Si es la primera vez, solicitará DNI y Nombre Completo.
3.  **Recolección de Datos:** Pedirá fechas (desde/hasta) y el motivo del trámite.
4.  **Carpeta Médica:** Preguntará si es por el propio agente o un familiar (solicitando datos del familiar si corresponde).
5.  **Confirmación:** Una vez completados los datos, el bot confirmará el registro y notificará que queda "Pendiente de revisión administrativa".
