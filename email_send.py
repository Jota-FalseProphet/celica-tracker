#!/usr/bin/env python3
"""Envío de correo del celica-tracker (verificación y reset de contraseña).

Transporte enchufable vía CELICA_MAIL_BACKEND:

  resend  (por defecto)  → API de Resend, reusa la cuenta de Sefer.
                           Necesita CELICA_RESEND_API_KEY.
  smtp                   → SMTP plano (para el mailserver propio
                           mail.yostesis.online cuando esté operativo).
                           Usa CELICA_SMTP_HOST/PORT/USER/PASSWORD.

El remitente por defecto es noreply@yostesis.online (dominio ya verificado en
Resend). Cuando levantes el docker-mailserver, basta con
CELICA_MAIL_BACKEND=smtp y sus credenciales: el resto del código no cambia.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

BACKEND   = os.environ.get("CELICA_MAIL_BACKEND", "resend").lower()
MAIL_FROM = os.environ.get("CELICA_MAIL_FROM", "Celica Tracker <noreply@yostesis.online>")

# Resend
RESEND_API_KEY = os.environ.get("CELICA_RESEND_API_KEY") or os.environ.get("RESEND_API_KEY", "")

# SMTP (mailserver propio)
SMTP_HOST = os.environ.get("CELICA_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("CELICA_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("CELICA_SMTP_USER", "")
SMTP_PASS = os.environ.get("CELICA_SMTP_PASSWORD", "")


def _html(title, intro, code, note):
    return f"""
    <div style="font-family:-apple-system,system-ui,sans-serif;max-width:440px;margin:0 auto;
                background:#16110d;color:#e8ddd0;padding:40px;border-radius:14px;
                border:1px solid #2a2018;">
        <h1 style="color:#e23b3b;font-size:1.4rem;margin:0 0 4px;">Celica Tracker</h1>
        <p style="color:#9a8a78;font-size:.85rem;margin:0 0 24px;">{title}</p>
        <p style="margin:0 0 20px;">{intro}</p>
        <div style="background:#1f1812;border:1px solid #33271c;border-radius:10px;
                    padding:20px;text-align:center;margin:0 0 22px;">
            <span style="font-size:2rem;font-weight:700;letter-spacing:8px;color:#ffa94d;">{code}</span>
        </div>
        <p style="color:#9a8a78;font-size:.8rem;margin:0;">{note}</p>
    </div>
    """


def _send(to_email, subject, html):
    if BACKEND == "smtp":
        _send_smtp(to_email, subject, html)
    else:
        _send_resend(to_email, subject, html)


def _send_resend(to_email, subject, html):
    import resend
    if not RESEND_API_KEY:
        raise RuntimeError("CELICA_RESEND_API_KEY no configurada")
    resend.api_key = RESEND_API_KEY
    resend.Emails.send({
        "from": MAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html,
    })


def _send_smtp(to_email, subject, html):
    if not SMTP_HOST:
        raise RuntimeError("CELICA_SMTP_HOST no configurado")
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("Tu cliente no soporta HTML. Revisa el código en la web.")
    msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(context=ctx)
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)


def send_verification_email(to_email, code):
    _send(to_email, "Celica Tracker · código de verificación",
          _html("Verificación de cuenta",
                "Tu código para activar la cuenta es:", code,
                "Caduca en 10 minutos. Si no te registraste, ignora este correo."))


def send_reset_email(to_email, code):
    _send(to_email, "Celica Tracker · restablecer contraseña",
          _html("Restablecer contraseña",
                "Tu código para cambiar la contraseña es:", code,
                "Caduca en 10 minutos. Si no lo pediste, ignora este correo."))
