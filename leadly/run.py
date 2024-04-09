from flask_migrate import init, migrate, upgrade

from leadly import create_app
from leadly.config import Config

app = create_app(Config)

if __name__ == "__main__":
    app.logger.info("Starting the application...")
    app.run(port=5001)


@app.cli.command("db_init")
def init_db():
    init(directory="migrations")


@app.cli.command("db_migrate")
def migrate_db():
    migrate(directory="migrations", message="New migration")


@app.cli.command("db_upgrade")
def upgrade_db():
    upgrade(directory="migrations")
