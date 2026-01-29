import azure.functions as func
import json
import os
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from shared.db import get_container
from shared.response import response, CORS_HEADERS

bp = func.Blueprint()

NOTIFY_EMAIL = "doniben@esperanto.co"
API_URL = "https://ludilo-api.azurewebsites.net/api"


def get_queued_count():
    """Count songs with status 'queued' in Cosmos DB."""
    container = get_container("songs")
    items = list(container.query_items(
        "SELECT VALUE COUNT(1) FROM c WHERE c.status = 'queued'",
        enable_cross_partition_query=True
    ))
    return items[0] if items else 0


def get_notify_flag():
    """Check if notification flag is active."""
    try:
        container = get_container("worker_status")
        items = list(container.query_items(
            "SELECT * FROM c WHERE c.id = 'notify_flag'",
            enable_cross_partition_query=True
        ))
        return items[0].get("active", False) if items else False
    except:
        return False


def set_notify_flag(active):
    """Set notification flag."""
    try:
        container = get_container("worker_status")
        container.upsert_item({"id": "notify_flag", "active": active})
    except:
        pass


def stop_aci():
    """Stop ACI container group if running."""
    try:
        from azure.mgmt.containerinstance import ContainerInstanceManagementClient
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        sub_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
        if not sub_id:
            return
        client = ContainerInstanceManagementClient(credential, sub_id)
        client.container_groups.stop("rg-ludilo", "ludilo-worker")
        logging.info("ACI stopped")
    except Exception as e:
        logging.info(f"ACI stop (may not exist yet): {e}")


def send_queue_notification(count):
    """Send email with queue count and ACI start link."""
    start_link = f"{API_URL}/aci/start?key={os.environ.get('ACI_SECRET', 'ludilo2026')}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, sans-serif; background-color: #0a0a0f; padding: 20px;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #12121a; padding: 32px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.1);">
    <h1 style="color: #06ffd2; font-size: 24px; margin: 0 0 8px 0;">Ludilo</h1>
    <p style="color: #9ca3af; font-size: 14px; margin: 0 0 24px 0;">Canciones en cola</p>
    
    <div style="background-color: #1a1a26; border-radius: 12px; padding: 20px; margin-bottom: 16px;">
      <p style="color: #ffffff; font-size: 48px; font-weight: bold; margin: 0;">{count}</p>
      <p style="color: #9ca3af; font-size: 14px; margin: 4px 0 0 0;">audios esperando</p>
    </div>
    
    <a href="{start_link}" style="display: block; text-align: center; background: linear-gradient(135deg, #06ffd2, #ff06c4); color: #000; font-weight: bold; font-size: 16px; padding: 16px 32px; border-radius: 12px; text-decoration: none; margin-bottom: 16px;">
      Iniciar Worker (ACI)
    </a>
    
    <p style="color: #4b5563; font-size: 12px; margin-top: 24px;">Se verifica cada 5 min mientras haya audios en cola.</p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart()
    msg['From'] = "sai@esperanto.co"
    msg['To'] = NOTIFY_EMAIL
    msg['Subject'] = f"Ludilo: {count} audio{'s' if count != 1 else ''} en cola"
    msg.attach(MIMEText(html, 'html'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login("sai@esperanto.co", os.environ.get("SMTP_PASSWORD", ""))
    server.sendmail("sai@esperanto.co", NOTIFY_EMAIL, msg.as_string())
    server.quit()


# ─── Timer 1: Cada hora — activa/desactiva notificaciones ─────────────────────

@bp.timer_trigger(schedule="0 0 * * * *", arg_name="timer", run_on_startup=False)
def hourly_check(timer: func.TimerRequest) -> None:
    """Cada hora: si hay audios en cola, activa timer de 5 min. Si no, apaga todo."""
    count = get_queued_count()
    logging.info(f"Hourly check: {count} en cola")

    if count > 0:
        set_notify_flag(True)
        logging.info("Notify flag activated")
    else:
        set_notify_flag(False)
        stop_aci()
        logging.info("Cola vacia. Flag off, ACI stopped.")


# ─── Timer 2: Cada 5 min — envía email si flag activo ─────────────────────────

@bp.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False)
def notify_check(timer: func.TimerRequest) -> None:
    """Cada 5 min: si flag activo y hay audios, enviar email."""
    if not get_notify_flag():
        return

    count = get_queued_count()
    if count == 0:
        set_notify_flag(False)
        stop_aci()
        logging.info("Cola vacia. Desactivando notificaciones y ACI.")
        return

    logging.info(f"Notify: {count} audios en cola. Enviando email.")
    try:
        send_queue_notification(count)
    except Exception as e:
        logging.error(f"Email error: {e}")


# ─── Endpoint: Levantar ACI ───────────────────────────────────────────────────

@bp.function_name("aci_start")
@bp.route(route="aci/start", methods=["GET", "OPTIONS"])
def start_aci(req: func.HttpRequest) -> func.HttpResponse:
    """Levantar ACI worker desde link del email."""
    if req.method == "OPTIONS":
        return response({}, 200)

    key = req.params.get("key", "")
    if key != os.environ.get("ACI_SECRET", "ludilo2026"):
        return response({"error": "unauthorized"}, 401)

    try:
        from azure.mgmt.containerinstance import ContainerInstanceManagementClient
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.containerinstance.models import (
            ContainerGroup, Container, ContainerGroupRestartPolicy,
            ResourceRequirements, ResourceRequests, ImageRegistryCredential,
            EnvironmentVariable, OperatingSystemTypes
        )

        credential = DefaultAzureCredential()
        sub_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
        client = ContainerInstanceManagementClient(credential, sub_id)

        # Check if already running
        try:
            group = client.container_groups.get("rg-ludilo", "ludilo-worker")
            if group.instance_view and group.instance_view.state == "Running":
                html = """<!DOCTYPE html><html><head><meta http-equiv="refresh" content="2;url=http://localhost:5173/aci/logs"></head><body style="font-family:sans-serif;background:#0a0a0f;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;">
                <div style="text-align:center;"><h1 style="color:#06ffd2;">Worker ya activo</h1><p>Redirigiendo a logs...</p></div></body></html>"""
                return func.HttpResponse(html, mimetype="text/html")
        except:
            pass

        # Delete if exists, then recreate
        try:
            client.container_groups.begin_delete("rg-ludilo", "ludilo-worker").wait()
        except:
            pass

        container = Container(
            name="worker",
            image="ludiloacr.azurecr.io/ludilo-worker:cpu-v3",
            resources=ResourceRequirements(requests=ResourceRequests(cpu=8, memory_in_gb=16)),
            environment_variables=[EnvironmentVariable(name="LUDILO_AUTO_STOP", value="120")]
        )
        group = ContainerGroup(
            location="eastus",
            containers=[container],
            os_type=OperatingSystemTypes.LINUX,
            restart_policy=ContainerGroupRestartPolicy.NEVER,
            image_registry_credentials=[ImageRegistryCredential(
                server="ludiloacr.azurecr.io",
                username="ludiloacr",
                password=os.environ.get("ACR_PASSWORD", "")
            )]
        )
        client.container_groups.begin_create_or_update("rg-ludilo", "ludilo-worker", group)

        html = """<!DOCTYPE html><html><head><meta http-equiv="refresh" content="2;url=http://localhost:5173/aci/logs"></head><body style="font-family:sans-serif;background:#0a0a0f;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;">
        <div style="text-align:center;"><h1 style="color:#06ffd2;">Worker iniciado</h1><p>Redirigiendo a logs...</p></div></body></html>"""
        return func.HttpResponse(html, mimetype="text/html")
    except Exception as e:
        html = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;background:#0a0a0f;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;">
        <div style="text-align:center;"><h1 style="color:#fbbf24;">ACI pendiente de configurar</h1><p>{str(e)[:200]}</p></div></body></html>"""
        return func.HttpResponse(html, mimetype="text/html")


@bp.function_name("aci_logs")
@bp.route(route="aci/logs", methods=["GET", "OPTIONS"])
def aci_logs(req: func.HttpRequest) -> func.HttpResponse:
    """Return ACI container logs as JSON."""
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    try:
        from azure.mgmt.containerinstance import ContainerInstanceManagementClient
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        sub_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
        client = ContainerInstanceManagementClient(credential, sub_id)

        # Get container state
        group = client.container_groups.get("rg-ludilo", "ludilo-worker")
        state = group.instance_view.state if group.instance_view else "Unknown"

        # Get logs
        logs = client.containers.list_logs("rg-ludilo", "ludilo-worker", "worker")
        content = logs.content or ""

        # Clean tqdm float noise (35.099999 → 35.1)
        import re
        content = re.sub(r'(\d+\.\d)\d{5,}', r'\1', content)

        return response({"state": state, "logs": content})
    except Exception as e:
        err = str(e)
        if "InternalServerError" in err or "not ready" in err:
            return response({"state": "Starting", "logs": ""})
        return response({"state": "error", "logs": err})
