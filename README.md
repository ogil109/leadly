Summary:
--------

My Flask app integrates with HubSpot for OAuth authentication. It allows users to log in using HubSpot, fetches and stores OAuth tokens, and automatically refreshes these tokens before they expire using token refresh jobs handled by APScheduler. Logging is in place to keep track of app activities, and I manage database migrations using Flask-Migrate. All app configurations, including HubSpot details, are stored in a separate configuration file. Sensitive data is stored as environment variables.

Design choices:
---------------

One of the core features of my app is its integration with HubSpot for authentication without relying on Flask-Session or any other login (I debated on this for sometime). This not only provides a seamless login experience but also ensures secure access to HubSpot's resources. The token refresh mechanism was an absolute necessity; it ensures that the user remains authenticated by automatically refreshing the token before it expires. If the user wants to logout, the route handles not only the Token removal, but also the refresh job removal.

Safety:
-------

To prevent CSRF attacks, a state parameter generated during the AuthRequest and HubSpot auth url construction is handled and then retrieved during the callback to see if it matches the user's one.

Here's the breakdown of my Flask app:

`__init__.py`:
--------------

### Extensions Initialization:

-   I've set up SQLAlchemy for database operations.
-   LoginManager manages user sessions for my login functionality.
-   I use APScheduler to schedule tasks at specific times.
-   Migrate is there to handle database migrations.

### App Factory:

-   I've defined a `create_app` function to create and configure the Flask app instance.
-   Extensions are initialized within this function.
-   I've also set up logging to write logs to a file.
-   I've registered a blueprint from `views.py` with the app.
-   A user loader callback is defined for Flask-Login.

* * * * *

`models.py`:
------------

### Token Model:

-   This model represents OAuth tokens.
-   It contains methods to refresh tokens and check if a user is authenticated.
-   Tokens are refreshed from HubSpot.

### TokenRefreshJob Model:

-   Represents scheduled jobs for token refresh.
-   Contains methods to create, reschedule, and remove refresh jobs.

### AuthRequest Model:

-   Represents authentication requests.
-   I use it to store UUIDs and create User IDs.

* * * * *

`oauth.py`:
-----------

### OAuth Functions:

-   `get_hubspot_auth_url`: Generates the HubSpot authentication URL.
-   `get_token_from_code`: Fetches a token using an authorization code and schedules a refresh job for the token.

* * * * *

`views.py`:
-----------

### Blueprint Creation:

-   I've created a blueprint named `main` for routing.

### Routes:

-   `/`: Displays the user ID and seconds until the token refresh if the user is authenticated. Otherwise, redirects to the login page.
-   `/login`: Redirects authenticated users to the index or generates a HubSpot authentication URL for unauthenticated users.
-   `/oauth-callback/`: Handles the OAuth callback from HubSpot, fetches the token, and redirects to the index.
-   `/logout`: Logs out the user and redirects to the index.

* * * * *

`config.py`:
------------

### Configuration Class:

-   Contains configurations for Flask, the database, HubSpot, and APScheduler.

* * * * *

`run.py`:
---------

### App Creation and Running:

-   I've created the Flask app using the `create_app` function.
-   The app runs on port 5000.
-   I've defined CLI commands for database initialization, migration, and upgrade.