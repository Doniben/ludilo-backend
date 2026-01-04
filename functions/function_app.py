import azure.functions as func
from routes.auth import bp as auth_bp
from routes.health import bp as health_bp
from routes.upload import bp as upload_bp

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
app.register_functions(auth_bp)
app.register_functions(health_bp)
app.register_functions(upload_bp)
