# Semana 06 — Agente del Laboratorio de Cómputo

## 1. Arquitectura general

El agente implementa un bucle **ReAct** (`Pensamiento → Acción → Observación`,
repetido hasta `FINAL:` o hasta agotar `MAX_VUELTAS = 5`) en `scripts/agente_laboratorio.py`,
usando únicamente la biblioteca estándar de Python 3 (`urllib.request`, `json`,
`os`, `ssl`, `re`). El estado del laboratorio (puestos, disponibilidad,
reservas) vive en memoria como diccionarios y listas, sin servidor ni
persistencia externa, tal como exige el reto.

### 1.1 "Cerebro" del agente: real vs. simulado

El agente separa el **razonamiento** (decidir la siguiente acción) de la
**ejecución de herramientas**. Para el razonamiento hay dos rutas:

- **`_cerebro_real`**: si existen las variables de entorno `PROVEEDOR`
  (`google`, `groq`, `openai` o `anthropic`) y `API_KEY`, el agente llama al
  proveedor real por HTTP usando exclusivamente `urllib.request` + `ssl` (sin
  SDKs de terceros), enviando el `SYSTEM_PROMPT` y el historial completo de la
  conversación (memoria de contexto). Google AI Studio (`gemini-3.5-flash-lite`)
  y Groq (`qwen/qwen3.8-27b`) se consumen por su endpoint compatible con OpenAI;
  el modelo se puede cambiar con la variable `MODELO`.
- **Respaldo ante fallas**: si la llamada real lanza cualquier excepción (sin
  red, key inválida, cuota agotada), el bucle imprime `[AVISO]` y usa el modo
  simulado en esa vuelta, de modo que el agente nunca se cae.
- **`_cerebro_simulado`**: si no hay credenciales configuradas (caso por
  defecto y el usado para las cuatro pruebas de este documento), una máquina
  de estados determinista decide la siguiente acción a partir de patrones
  reconocibles en la solicitud (franjas horarias, códigos de estudiante,
  ids de reserva, intención de cancelar) y de lo que ya se observó en turnos
  previos. Esto garantiza pruebas 100% reproducibles sin conexión, tal como
  pide el reto ("modo simulado de respaldo para pruebas sin conexión").

Se optó por este diseño de dos rutas —en lugar de exigir siempre un LLM
real— porque el reto explícitamente no requiere conectividad externa ni
servidor mock, y una máquina de estados simple es suficiente para cubrir
de forma fiable los flujos de negocio exigidos, dejando la puerta abierta a
un LLM real como extensión sin cambiar el resto del agente (las herramientas,
el protocolo `ACCION:`/`FINAL:` y el bucle son idénticos en ambas rutas).

### 1.2 System Prompt y rol

El `SYSTEM_PROMPT` (ver código) define:

- **Rol**: Agente de Operaciones del Laboratorio de Cómputo.
- **Reglas duras de negocio**: horario estricto 06:00-20:00 en franjas de 2h
  (fuera de horario, responder `FINAL` directo sin tocar herramientas), máximo
  1 reserva activa por estudiante, y prohibición de confirmar una cancelación
  sin autorización humana previa.
- **Protocolo ReAct**: cada turno debe terminar en `ACCION: herramienta:parametro`
  o `FINAL: respuesta`.

### 1.3 Herramientas y Human-in-the-loop

Tres herramientas puras (`HERRAMIENTAS` en el código):

| Herramienta | Efecto | Control humano |
|---|---|---|
| `consultar_disponibilidad(franja)` | Lee `DISPONIBILIDAD`; si la franja no es válida, avisa cierre | No requiere |
| `consultar_reserva(codigo_estudiante)` | Lee `RESERVAS` | No requiere |
| `cancelar_reserva(id_reserva)` | Muta `RESERVAS` (borra la entrada) | **Obligatorio**: pide `input()` `[CONTROL-HUMANO] ¿Autorizas cancelar la reserva {id}? (s/n):` antes de aplicar cualquier cambio. Si la respuesta no es `s`, la reserva **no** se toca. |

Solo `cancelar_reserva` muta estado, y es la única herramienta con
salvaguarda humana — coherente con que es la única acción destructiva.

### 1.4 Criterio de parada

- Éxito: el turno actual devuelve `FINAL:` → se imprime la respuesta y se
  retorna.
- Tope: si tras `MAX_VUELTAS = 5` turnos no hubo `FINAL:`, se imprime
  `[PARADA] Tope alcanzado` y el agente termina sin inventar una respuesta.

En las cuatro pruebas de este documento el agente siempre resuelve en 1 a 3
turnos, muy por debajo del tope.

## 2. Trazas de las cuatro ejecuciones obligatorias

Todas las trazas fueron generadas ejecutando literalmente:

```
python scripts/agente_laboratorio.py "<solicitud>"
```

en modo simulado (sin `PROVEEDOR`/`API_KEY` definidas).

### 2.1 Misión 1 — Consulta compuesta de disponibilidad y horario

Comando: `python scripts/agente_laboratorio.py "¿Hay puestos disponibles en la franja 10:00-12:00 y el laboratorio está abierto en ese horario?"`

```
=== Solicitud: '¿Hay puestos disponibles en la franja 10:00-12:00 y el laboratorio está abierto en ese horario?' ===
[VUELTA 1] PENSAMIENTO: Debo verificar horario y disponibilidad de esa franja.
[VUELTA 1] ACCION: consultar_disponibilidad:10:00-12:00
[VUELTA 1] OBSERVACION: Puestos libres en 10:00-12:00: P-01, P-02, P-03, P-05, P-06
[VUELTA 2] PENSAMIENTO: Ya tengo la disponibilidad solicitada.
[VUELTA 2] FINAL: Puestos libres en 10:00-12:00: P-01, P-02, P-03, P-05, P-06
```

La franja es válida (cubre la parte de "horario") y la observación resuelve
también la parte de "disponibilidad" en una sola herramienta.

### 2.2 Misión 2a — Cancelación rechazada por el operador humano

Comando: `echo "n" | python scripts/agente_laboratorio.py "Quiero cancelar la reserva del estudiante E-101"`

```
=== Solicitud: 'Quiero cancelar la reserva del estudiante E-101' ===
[VUELTA 1] PENSAMIENTO: Primero necesito ubicar la reserva activa del estudiante.
[VUELTA 1] ACCION: consultar_reserva:E-101
[VUELTA 1] OBSERVACION: Estudiante E-101 tiene reservado el puesto P-04, franja 10:00-12:00, id de reserva RES-402
[VUELTA 2] PENSAMIENTO: Debo pedir autorización humana antes de cancelar la reserva.
[VUELTA 2] ACCION: cancelar_reserva:RES-402
[CONTROL-HUMANO] ¿Autorizas cancelar la reserva RES-402? (s/n): [VUELTA 2] OBSERVACION: Cancelación de reserva RES-402 rechazada por el operador humano.
[VUELTA 3] PENSAMIENTO: Ya tengo el resultado de la cancelación.
[VUELTA 3] FINAL: Cancelación de reserva RES-402 rechazada por el operador humano.
```

Al responder `n`, la reserva `RES-402` **permanece activa** — el agente no
alucina una cancelación exitosa.

### 2.3 Misión 2b — Cancelación aprobada por el operador humano

Comando: `echo "s" | python scripts/agente_laboratorio.py "Quiero cancelar la reserva del estudiante E-101"`

```
=== Solicitud: 'Quiero cancelar la reserva del estudiante E-101' ===
[VUELTA 1] PENSAMIENTO: Primero necesito ubicar la reserva activa del estudiante.
[VUELTA 1] ACCION: consultar_reserva:E-101
[VUELTA 1] OBSERVACION: Estudiante E-101 tiene reservado el puesto P-04, franja 10:00-12:00, id de reserva RES-402
[VUELTA 2] PENSAMIENTO: Debo pedir autorización humana antes de cancelar la reserva.
[VUELTA 2] ACCION: cancelar_reserva:RES-402
[CONTROL-HUMANO] ¿Autorizas cancelar la reserva RES-402? (s/n): [VUELTA 2] OBSERVACION: Reserva RES-402 cancelada exitosamente y puesto liberado.
[VUELTA 3] PENSAMIENTO: Ya tengo el resultado de la cancelación.
[VUELTA 3] FINAL: Reserva RES-402 cancelada exitosamente y puesto liberado.
```

Con `s`, la herramienta borra la entrada de `RESERVAS` y el puesto `P-04`
queda libre.

### 2.4 Misión 3 — Solicitud fuera de horario (rechazo sin invocar herramientas)

Comando: `python scripts/agente_laboratorio.py "Quiero reservar un puesto a las 22:00"`

```
=== Solicitud: 'Quiero reservar un puesto a las 22:00' ===
[VUELTA 1] PENSAMIENTO: La solicitud menciona una hora fuera del horario de atención.
[VUELTA 1] FINAL: Lo siento, el laboratorio está cerrado en ese horario (22:00). Atendemos de 06:00 a 20:00 en franjas de 2 horas.
```

El agente detecta que `22:00` está fuera de `[06:00, 20:00)` **antes** de
intentar cualquier `ACCION:` y responde `FINAL:` en el primer turno, sin
alucinar una llamada a `consultar_disponibilidad`.

## 3. Cómo reproducir

```bash
cd semana06
python scripts/agente_laboratorio.py "¿Hay puestos disponibles en la franja 10:00-12:00 y el laboratorio está abierto en ese horario?"
echo "n" | python scripts/agente_laboratorio.py "Quiero cancelar la reserva del estudiante E-101"
echo "s" | python scripts/agente_laboratorio.py "Quiero cancelar la reserva del estudiante E-101"
python scripts/agente_laboratorio.py "Quiero reservar un puesto a las 22:00"
```

Con LLM real (gratis, sin tarjeta), en PowerShell:

```powershell
$env:PROVEEDOR="google"; $env:API_KEY="<tu_key_de_AI_Studio>"
python scripts/agente_laboratorio.py "¿Hay puestos disponibles en la franja 10:00-12:00?"
```

Nota: cada ejecución es un proceso nuevo, por lo que el estado de `RESERVAS`
se reinicia entre pruebas (la 2a y la 2b parten ambas de que `E-101` tiene la
reserva `RES-402` activa).
