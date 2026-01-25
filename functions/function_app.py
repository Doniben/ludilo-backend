import azure.functions as func
from routes.auth import bp as auth_bp
from routes.health import bp as health_bp
from routes.upload import bp as upload_bp
from routes.timer import bp as timer_bp
from routes.library import bp as library_bp
from routes.worker import worker_bp

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
app.register_functions(auth_bp)
app.register_functions(health_bp)
app.register_functions(upload_bp)
app.register_functions(timer_bp)
app.register_functions(library_bp)
app.register_functions(worker_bp)
