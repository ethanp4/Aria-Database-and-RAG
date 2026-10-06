$env:PGPASSWORD = "pass"
psql -U postgres -c "DROP DATABASE IF EXISTS aria;"
psql -U postgres -c "CREATE DATABASE aria;"