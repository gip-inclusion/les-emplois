echo <<EOF >>/var/lib/postgresql/data/postgresql.conf
# Non-durable settings
# https://www.postgresql.org/docs/current/non-durability.html
fsync=off
synchronous_commit=off
full_pages_write=off
max_wal_size=1GB
checkpoint_timeout=1d
EOF
# Used by the pg_isready health check.
createuser -s root
createdb root
