#!/bin/bash
#
# Docker container initialization script.
#
# 2020-24 Jaroslaw Szczegielniak, Benjamin Kellenberger
#

# check required libraries
libCheck="$(python install/verify_installed_libs.py)"
if [ ${#libCheck} -gt 0 ]; then
    echo "The following libraries could not be imported: $libCheck"
    exit 1
fi

sudo systemctl enable redis-server.service
sudo service redis-server start 

echo "============================="
echo "Setup of database IS STARTING"
echo "============================="
pgVersion=12
dbName=$(python util/configDef.py --section=Database --parameter=name) 
dbUser=$(python util/configDef.py --section=Database --parameter=user)
dbPassword=$(python util/configDef.py --section=Database --parameter=password)
dbPort=$(python util/configDef.py --section=Database --parameter=port)
sudo sed -i "s/\s*port\s*=\s[0-9]*/port = $dbPort/g" /etc/postgresql/$pgVersion/main/postgresql.conf
sudo service postgresql restart

sudo -u postgres psql -p $dbPort -tc "SELECT 1 FROM pg_roles WHERE pg_roles.rolname='$dbUser'" | grep -q 1 || sudo -u postgres psql -p $dbPort -c "CREATE USER \"$dbUser\" WITH PASSWORD '$dbPassword';"
sudo -u postgres psql -p $dbPort -tc "SELECT 1 FROM pg_database WHERE datname = '$dbName'" | grep -q 1 || sudo -u postgres psql -p $dbPort -c "CREATE DATABASE \"$dbName\" WITH OWNER \"$dbUser\" CONNECTION LIMIT -1;"
sudo -u postgres psql -p $dbPort -c "GRANT CREATE, CONNECT ON DATABASE \"$dbName\" TO \"$dbUser\";"
sudo -u postgres psql -p $dbPort -d $dbName -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"
sudo -u postgres psql -p $dbPort -d $dbName -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO \"$dbUser\";"
sudo -u postgres psql -p $dbPort -d $dbName -c "CREATE EXTENSION IF NOT EXISTS postgis;"

# Create DB schema
python setup/setup_database.py
sudo systemctl enable postgresql.service
sudo service postgresql start

echo "=============================="
echo "Setup of database IS COMPLETED"
echo "=============================="
echo ""

echo "=========================="
echo "RABBITMQ SETUP IS STARTING"
echo "=========================="
# I need to set rabbitmq user and permissions here, as it takes hostname (dynamic) during build of previous phases as part of config folder :-()
RMQ_username=aide
RMQ_password=password # This should never be left here for any serious use of course
sudo service rabbitmq-server start
# add the user we defined above
sudo rabbitmqctl list_users|grep -q $RMQ_username || sudo rabbitmqctl add_user $RMQ_username $RMQ_password

# add new virtual host
sudo rabbitmqctl list_vhosts|grep -q 'aide_vhost' || sudo rabbitmqctl add_vhost aide_vhost

# set permissions
sudo rabbitmqctl set_permissions -p aide_vhost $RMQ_username ".*" ".*" ".*"
sudo systemctl enable rabbitmq-server.service
echo "==========================="
echo "RABBITMQ SETUP IS COMPLETED"
echo "==========================="
echo ""
# If AIDE is run on MS Azure: TCP connections are dropped after 4 minutes of inactivity
# (see https://docs.microsoft.com/en-us/azure/load-balancer/load-balancer-outbound-connections#idletimeout)
# This is fatal for our database connection system, which keeps connections open.
# To avoid idling/dead connections, we thus use Ubuntu's keepalive timer:
if ! grep -q ^net.ipv4.tcp_keepalive_* /etc/sysctl.conf ; then
    echo "net.ipv4.tcp_keepalive_time = 60" | tee -a "/etc/sysctl.conf" > /dev/null
    echo "net.ipv4.tcp_keepalive_intvl = 60" | tee -a "/etc/sysctl.conf" > /dev/null
    echo "net.ipv4.tcp_keepalive_probes = 20" | tee -a "/etc/sysctl.conf" > /dev/null
else
    sed -i "s/^\s*net.ipv4.tcp_keepalive_time.*/net.ipv4.tcp_keepalive_time = 60 /g" /etc/sysctl.conf
    sed -i "s/^\s*net.ipv4.tcp_keepalive_intvl.*/net.ipv4.tcp_keepalive_intvl = 60 /g" /etc/sysctl.conf
    sed -i "s/^\s*net.ipv4.tcp_keepalive_probes.*/net.ipv4.tcp_keepalive_probes = 20 /g" /etc/sysctl.conf
fi
sysctl -p

# file server: static files directory
fsDir=$(python util/configDef.py --section=FileServer --parameter=staticfiles_dir --fallback=/opt/aide/data) 
mkdir -p $fsDir
