# Admin dashboard (/admin)

A web page for Quadralens: every farm (owner, members, animals, barns, last activity), every user and their farms,
the totals, and deleting a farm. It is **off** until a password is set.

## Turn it on (server)

1. In `/home/ubuntu/farmivo/farmivo_backend/.env` add a long password of your choice:

       FARMIVO_ADMIN_PASSWORD=<a long random password>

2. `sudo supervisorctl restart farmivo`

## Open it from your PC by the server's address

In `.env` add (the password must have at least 12 characters):

    FARMIVO_ADMIN_ALLOW_REMOTE=true

then `sudo supervisorctl restart farmivo`, and open `http://51.83.71.157:8000/admin` (user `admin`).

Protection: an address that types 8 wrong passwords within 15 minutes is refused for 15 minutes. The API still
runs on plain HTTP, so the password travels readable on the network: use a password used nowhere else, and move
to HTTPS (deploy/nginx) as planned; nothing else changes then.

Without `FARMIVO_ADMIN_ALLOW_REMOTE` the page answers only requests made from the server itself; then open it
through an SSH tunnel: `ssh -L 8000:localhost:8000 ubuntu@51.83.71.157` (keep it open), and
`http://localhost:8000/admin`.

## Delete a farm

Farms › the farm › "Delete this farm": type the farm's name and confirm. Same deletion as `scripts/delete_farm.py`
and as the owner's "Delete farm" in the app: every record and photo of the farm; its people keep their account.
