import azure.functions as func
import json
import os
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from azure.storage.queue import QueueClient
from shared.db import get_container

bp = func.Blueprint()

NOTIFY_EMAIL = "doniben@esperanto.co"
ACI_ENABLED = False  # Cambiar a True cuando estemos listos para levantar ACI


def get_queue_count(queue_name):
    conn_str = os.environ["STORAGE_CONNECTION_STRING"]
    client = QueueClient.from_connection_string(conn_str, queue_name)
    props = client.get_queue_properties()
    return props.approximate_message_count


def is_worker_online():
    """Verifica si el worker local está activo (heartbeat < 2 min)."""
    from datetime import datetime, timezone, timedelta
    container = get_container("worker_status")
    try:
        items = list(container.query_items(
            "SELECT TOP 1 * FROM c ORDER BY c.timestamp DESC",
            enable_cross_partition_query=True
        ))
        if not items:
            return False
        last = datetime.fromisoformat(items[0]["timestamp"])
        return (datetime.now(timezone.utc) - last).total_seconds() < 120
    except Exception:
        return False


def send_notification(queue_count, worker_online):
    """Envía email con estado de la cola."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, sans-serif; background-color: #0a0a0f; padding: 20px;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #12121a; padding: 32px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.1);">
    <h1 style="color: #06ffd2; font-size: 24px; margin: 0 0 8px 0;">Ludilo</h1>
    <p style="color: #9ca3af; font-size: 14px; margin: 0 0 24px 0;">Reporte de cola de procesamiento</p>
    
    <div style="background-color: #1a1a26; border-radius: 12px; padding: 20px; margin-bottom: 16px;">
      <p style="color: #ffffff; font-size: 32px; font-weight: bold; margin: 0;">{queue_count}</p>
      <p style="color: #9ca3af; font-size: 14px; margin: 4px 0 0 0;">audios en cola</p>
    </div>
    
    <div style="background-color: #1a1a26; border-radius: 12px; padding: 20px; margin-bottom: 16px;">
      <p style="color: {'#06ffd2' if worker_online else '#ef4444'}; font-size: 14px; font-weight: 600; margin: 0;">
        Worker local: {'🟢 Online' if worker_online else '🔴 Offline'}
      </p>
    </div>
    
    {'<div style="background-color: rgba(6,255,210,0.05); border: 1px solid rgba(6,255,210,0.2); border-radius: 12px; padding: 16px;"><p style="color: #06ffd2; font-size: 14px; margin: 0;">⚡ ACI se levantaría aquí si estuviera habilitado.</p></div>' if not worker_online and queue_count > 0 and not ACI_ENABLED else ''}
    
    <p style="color: #4b5563; font-size: 12px; margin-top: 24px;">Este es un reporte automático cada 2 horas.</p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart()
    msg['From'] = "sai@esperanto.co"
    msg['To'] = NOTIFY_EMAIL
    msg['Subject'] = f"Ludilo: {queue_count} audios en cola"
    msg.attach(MIMEText(html, 'html'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login("sai@esperanto.co", os.environ.get("SMTP_PASSWORD", "gxqcbdgzysfeivio"))
    server.sendmail("sai@esperanto.co", NOTIFY_EMAIL, msg.as_string())
    server.quit()


@bp.timer_trigger(schedule="0 0 */2 * * *", arg_name="timer", run_on_startup=False)
def check_queue(timer: func.TimerRequest) -> None:
    """Cada 2 horas: verifica cola, notifica, y opcionalmente levanta ACI."""
    logging.info("Timer trigger: verificando cola de procesamiento")

    queue_free = get_queue_count("audio-processing-queue")
    queue_priority = get_queue_count("audio-processing-priority")
    total = queue_free + queue_priority

    if total == 0:
        logging.info("Cola vacía, nada que hacer.")
        return

    worker_online = is_worker_online()
    logging.info(f"Cola: {total} audios. Worker online: {worker_online}")

    # Enviar notificación
    try:
        send_notification(total, worker_online)
        logging.info(f"Email enviado a {NOTIFY_EMAIL}")
    except Exception as e:
        logging.error(f"Error enviando email: {e}")

    # ACI logic (deshabilitado por ahora)
    if ACI_ENABLED and not worker_online and total > 0:
        logging.info("Levantando Azure Container Instance...")
        # TODO: implementar start_aci()
        pass
