#!/usr/bin/env python3
"""Agente ReAct de operaciones del laboratorio de cómputo (Semana 06).

Solo biblioteca estándar de Python 3 (urllib.request, json, os, ssl).
Sin pip install, sin LangChain/CrewAI/LlamaIndex ni librerías de terceros.
"""

import json
import os
import re
import ssl
import urllib.request

MAX_VUELTAS = 5

FRANJAS_VALIDAS = [
    "06:00-08:00", "08:00-10:00", "10:00-12:00",
    "12:00-14:00", "14:00-16:00", "16:00-18:00", "18:00-20:00",
]

DISPONIBILIDAD = {
    "06:00-08:00": ["P-11", "P-12", "P-13", "P-14", "P-15"],
    "08:00-10:00": ["P-16", "P-17", "P-18"],
    "10:00-12:00": ["P-01", "P-02", "P-03", "P-05", "P-06"],
    "12:00-14:00": ["P-19", "P-20"],
    "14:00-16:00": ["P-07", "P-08", "P-09"],
    "16:00-18:00": ["P-01", "P-02", "P-03", "P-04", "P-05", "P-06"],
    "18:00-20:00": ["P-10", "P-11", "P-12", "P-13"],
}

RESERVAS = {
    "E-101": {"puesto": "P-04", "franja": "10:00-12:00", "id_reserva": "RES-402"},
    "E-102": {"puesto": "P-10", "franja": "14:00-16:00", "id_reserva": "RES-503"},
}

SYSTEM_PROMPT = """Eres el Agente de Operaciones del Laboratorio de Cómputo de la universidad.

Reglas duras de negocio (no negociables):
1. Horario estricto: el laboratorio opera en franjas de 2 horas entre las 06:00 y
   las 20:00 (franjas válidas: 06:00-08:00, 08:00-10:00, 10:00-12:00, 12:00-14:00,
   14:00-16:00, 16:00-18:00, 18:00-20:00). Fuera de ese horario el laboratorio está
   cerrado y NO debes invocar ninguna herramienta: responde FINAL directamente
   indicando el cierre.
2. Cada estudiante puede tener como máximo 1 reserva activa.
3. Nunca confirmes la cancelación de una reserva sin la autorización previa del
   operador humano, obtenida exclusivamente a través de la herramienta
   cancelar_reserva. No asumas ni inventes una aprobación.

Herramientas disponibles:
- consultar_disponibilidad:<franja> -> puestos libres en esa franja, o aviso de
  cierre si la franja no es válida.
- consultar_reserva:<codigo_estudiante> -> datos de la reserva activa del
  estudiante, si existe.
- cancelar_reserva:<id_reserva> -> solicita autorización humana y cancela la
  reserva solo si es aprobada.

Protocolo de razonamiento (ReAct):
En cada turno escribes tu razonamiento y luego EXACTAMENTE una de estas dos líneas:
  ACCION: herramienta:parametro   -> para usar una herramienta
  FINAL: respuesta                -> para entregar la respuesta definitiva

Tienes un máximo de 5 turnos. No inventes observaciones: espera siempre la
OBSERVACION real antes de continuar.
"""

FRANJA_RE = re.compile(r"\b(\d{2}:\d{2}-\d{2}:\d{2})\b")
HORA_SUELTA_RE = re.compile(r"\b(\d{2}):(\d{2})\b")
ESTUDIANTE_RE = re.compile(r"\bE-\d+\b", re.IGNORECASE)
RESERVA_RE = re.compile(r"\bRES-\d+\b", re.IGNORECASE)


# --------------------------------------------------------------------------
# Herramientas
# --------------------------------------------------------------------------

def consultar_disponibilidad(franja):
    franja = franja.strip()
    if franja not in FRANJAS_VALIDAS:
        return f"El laboratorio está cerrado en la franja {franja}. Horario válido: 06:00-20:00."
    libres = DISPONIBILIDAD.get(franja, [])
    if not libres:
        return f"No hay puestos libres en {franja}."
    return f"Puestos libres en {franja}: {', '.join(libres)}"


def consultar_reserva(codigo_estudiante):
    codigo_estudiante = codigo_estudiante.strip().upper()
    reserva = RESERVAS.get(codigo_estudiante)
    if not reserva:
        return f"El estudiante {codigo_estudiante} no tiene reservas activas."
    return (
        f"Estudiante {codigo_estudiante} tiene reservado el puesto "
        f"{reserva['puesto']}, franja {reserva['franja']}, "
        f"id de reserva {reserva['id_reserva']}"
    )


def cancelar_reserva(id_reserva):
    id_reserva = id_reserva.strip().upper()
    confirmacion = input(
        f"[CONTROL-HUMANO] ¿Autorizas cancelar la reserva {id_reserva}? (s/n): "
    ).strip().lower()
    if confirmacion != "s":
        return f"Cancelación de reserva {id_reserva} rechazada por el operador humano."
    for codigo, reserva in list(RESERVAS.items()):
        if reserva["id_reserva"] == id_reserva:
            del RESERVAS[codigo]
            return f"Reserva {id_reserva} cancelada exitosamente y puesto liberado."
    return f"No se encontró ninguna reserva activa con id {id_reserva}."


HERRAMIENTAS = {
    "consultar_disponibilidad": consultar_disponibilidad,
    "consultar_reserva": consultar_reserva,
    "cancelar_reserva": cancelar_reserva,
}


# --------------------------------------------------------------------------
# "Cerebro" del agente: llamada real a un LLM (opcional) o modo simulado
# --------------------------------------------------------------------------

def _cerebro_real(mensajes):
    """Llama a un proveedor LLM real por HTTP usando solo urllib/ssl/json.

    Se activa únicamente si existen las variables de entorno PROVEEDOR y
    API_KEY. Si la llamada falla por cualquier motivo, el llamador debe
    recurrir al modo simulado (ver _cerebro_simulado).
    """
    proveedor = os.environ.get("PROVEEDOR", "").lower()
    api_key = os.environ.get("API_KEY")
    if not proveedor or not api_key:
        return None

    contexto = ssl.create_default_context()

    if proveedor == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        cuerpo = json.dumps({
            "model": "claude-sonnet-5",
            "max_tokens": 300,
            "system": mensajes[0]["contenido"],
            "messages": [
                {"role": "user" if m["rol"] == "user" else "assistant", "content": m["contenido"]}
                for m in mensajes[1:]
            ],
        }).encode("utf-8")
        peticion = urllib.request.Request(url, data=cuerpo, method="POST", headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })
        with urllib.request.urlopen(peticion, context=contexto, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"]

    if proveedor == "openai":
        url = "https://api.openai.com/v1/chat/completions"
        cuerpo = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system" if m["rol"] == "system" else m["rol"], "content": m["contenido"]}
                for m in mensajes
            ],
        }).encode("utf-8")
        peticion = urllib.request.Request(url, data=cuerpo, method="POST", headers={
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
        })
        with urllib.request.urlopen(peticion, context=contexto, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    if proveedor in ("google", "groq"):
        # Endpoints compatibles con OpenAI (Google AI Studio / Groq, gratis).
        if proveedor == "google":
            url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            modelo = os.environ.get("MODELO", "gemini-3.5-flash-lite")
        else:
            url = "https://api.groq.com/openai/v1/chat/completions"
            modelo = os.environ.get("MODELO", "qwen/qwen3.8-27b")
        cuerpo = json.dumps({
            "model": modelo,
            "temperature": 0,
            "messages": [{"role": m["rol"], "content": m["contenido"]} for m in mensajes],
        }).encode("utf-8")
        peticion = urllib.request.Request(url, data=cuerpo, method="POST", headers={
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
        })
        with urllib.request.urlopen(peticion, context=contexto, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    return None


def _franja_fuera_de_horario(entrada):
    """Detecta si la solicitud menciona una franja o una hora fuera de 06:00-20:00."""
    m = FRANJA_RE.search(entrada)
    if m:
        return m.group(1) if m.group(1) not in FRANJAS_VALIDAS else None
    for hh, mm in HORA_SUELTA_RE.findall(entrada):
        hora = int(hh)
        if hora < 6 or hora >= 20:
            return f"{hh}:{mm}"
    return None


def _cerebro_simulado(entrada, contexto_estado):
    """Reasoning determinista que respeta el protocolo ACCION:/FINAL:.

    No es un LLM: es una máquina de estados simple pensada para resolver de
    forma reproducible las solicitudes propias del dominio del laboratorio,
    útil para pruebas sin conexión (sin PROVEEDOR/API_KEY configurados).
    """
    fuera_de_horario = _franja_fuera_de_horario(entrada)
    if fuera_de_horario and contexto_estado.get("disponibilidad") is None:
        return (
            "La solicitud menciona una hora fuera del horario de atención.",
            "FINAL",
            f"Lo siento, el laboratorio está cerrado en ese horario ({fuera_de_horario}). "
            "Atendemos de 06:00 a 20:00 en franjas de 2 horas.",
        )

    quiere_cancelar = "cancel" in entrada.lower()
    estudiante_m = ESTUDIANTE_RE.search(entrada)
    reserva_m = RESERVA_RE.search(entrada)

    if quiere_cancelar:
        if contexto_estado.get("cancelacion") is not None:
            return ("Ya tengo el resultado de la cancelación.", "FINAL", contexto_estado["cancelacion"])
        id_reserva = None
        if reserva_m:
            id_reserva = reserva_m.group(0).upper()
        elif contexto_estado.get("reserva_id"):
            id_reserva = contexto_estado["reserva_id"]
        if id_reserva:
            return (
                "Debo pedir autorización humana antes de cancelar la reserva.",
                "ACCION",
                f"cancelar_reserva:{id_reserva}",
            )
        if estudiante_m and contexto_estado.get("reserva_id") is None:
            return (
                "Primero necesito ubicar la reserva activa del estudiante.",
                "ACCION",
                f"consultar_reserva:{estudiante_m.group(0).upper()}",
            )
        return (
            "No tengo suficiente información para identificar la reserva.",
            "FINAL",
            "Necesito el código de estudiante o el id de la reserva para poder cancelarla.",
        )

    franja_m = FRANJA_RE.search(entrada)
    if franja_m and contexto_estado.get("disponibilidad") is None:
        return (
            "Debo verificar horario y disponibilidad de esa franja.",
            "ACCION",
            f"consultar_disponibilidad:{franja_m.group(1)}",
        )
    if contexto_estado.get("disponibilidad") is not None:
        return ("Ya tengo la disponibilidad solicitada.", "FINAL", contexto_estado["disponibilidad"])

    if estudiante_m and contexto_estado.get("reserva") is None:
        return (
            "Debo consultar la reserva activa del estudiante.",
            "ACCION",
            f"consultar_reserva:{estudiante_m.group(0).upper()}",
        )
    if contexto_estado.get("reserva") is not None:
        return ("Ya tengo los datos de la reserva.", "FINAL", contexto_estado["reserva"])

    return (
        "No identifico franja horaria, código de estudiante ni número de reserva en la solicitud.",
        "FINAL",
        "No entendí la solicitud. Indica una franja horaria (ej. 10:00-12:00), "
        "un código de estudiante (ej. E-101) o un id de reserva (ej. RES-402).",
    )


# --------------------------------------------------------------------------
# Bucle ReAct
# --------------------------------------------------------------------------

def ejecutar_agente(entrada_usuario):
    print(f"\n=== Solicitud: {entrada_usuario!r} ===")
    mensajes = [{"rol": "system", "contenido": SYSTEM_PROMPT}, {"rol": "user", "contenido": entrada_usuario}]
    contexto_estado = {}

    for vuelta in range(1, MAX_VUELTAS + 1):
        try:
            respuesta_real = _cerebro_real(mensajes)
        except Exception as error:  # red caída, key inválida, cuota, etc.
            print(f"[AVISO] Falla del proveedor LLM ({error}); uso modo simulado.")
            respuesta_real = None
        if respuesta_real is not None:
            pensamiento, tipo, contenido = _parsear_respuesta_llm(respuesta_real)
        else:
            pensamiento, tipo, contenido = _cerebro_simulado(entrada_usuario, contexto_estado)

        print(f"[VUELTA {vuelta}] PENSAMIENTO: {pensamiento}")

        if tipo == "FINAL":
            print(f"[VUELTA {vuelta}] FINAL: {contenido}")
            return contenido

        herramienta, _, parametro = contenido.partition(":")
        print(f"[VUELTA {vuelta}] ACCION: {herramienta}:{parametro}")

        funcion = HERRAMIENTAS.get(herramienta)
        if funcion is None:
            observacion = f"Herramienta desconocida: {herramienta}"
        else:
            observacion = funcion(parametro)

        print(f"[VUELTA {vuelta}] OBSERVACION: {observacion}")
        mensajes.append({"rol": "assistant", "contenido": f"{pensamiento}\nACCION: {herramienta}:{parametro}"})
        mensajes.append({"rol": "user", "contenido": f"OBSERVACION: {observacion}"})

        if herramienta == "consultar_disponibilidad":
            contexto_estado["disponibilidad"] = observacion
        elif herramienta == "consultar_reserva":
            contexto_estado["reserva"] = observacion
            m = RESERVA_RE.search(observacion)
            if m:
                contexto_estado["reserva_id"] = m.group(0).upper()
        elif herramienta == "cancelar_reserva":
            contexto_estado["cancelacion"] = observacion

    print("[PARADA] Tope alcanzado")
    return None


def _parsear_respuesta_llm(texto):
    """Extrae (pensamiento, tipo, contenido) de la respuesta cruda de un LLM real."""
    accion_m = re.search(r"ACCION:\s*(.+)", texto)
    final_m = re.search(r"FINAL:\s*(.+)", texto)
    pensamiento = texto.split("ACCION:")[0].split("FINAL:")[0].strip() or "(sin razonamiento explícito)"
    if final_m:
        return pensamiento, "FINAL", final_m.group(1).strip()
    if accion_m:
        return pensamiento, "ACCION", accion_m.group(1).strip()
    return pensamiento, "FINAL", texto.strip()


def main():
    import sys

    if len(sys.argv) > 1:
        entrada = " ".join(sys.argv[1:])
    else:
        entrada = input("Solicitud del estudiante: ").strip()
    ejecutar_agente(entrada)


if __name__ == "__main__":
    main()
