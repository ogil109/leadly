Summary:
--------

My Flask app integrates with HubSpot for OAuth authentication. It allows users to log in using HubSpot, fetches and stores OAuth tokens, and automatically refreshes these tokens before they expire using token refresh jobs handled by APScheduler. Logging is in place to keep track of app activities, and I manage database migrations using Flask-Migrate. All app configurations, including HubSpot details, are stored in a separate configuration file. Sensitive data is stored as environment variables.

Safety:
-------

To prevent CSRF attacks, a state parameter generated during the AuthRequest and HubSpot auth url construction is handled and then retrieved during the callback to see if it matches the user's one.
