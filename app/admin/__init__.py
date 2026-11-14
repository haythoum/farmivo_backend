"""Admin web dashboard for Quadralens (/admin): every farm and user, their size and activity, and deleting a farm.

Off until ``FARMIVO_ADMIN_PASSWORD`` is set. Then it asks for user ``admin`` and that password (HTTP Basic) and,
unless ``FARMIVO_ADMIN_ALLOW_REMOTE=true``, answers only requests made from the server itself, so the password
never crosses the network in clear: open it through an SSH tunnel (see docs/ADMIN.md).
"""
