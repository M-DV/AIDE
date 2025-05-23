#
# AIDE main Dockerfile.
#
# 2020-24 Jaroslaw Szczegielniak, Benjamin Kellenberger
FROM nvidia/cuda:12.6.2-cudnn-devel-ubuntu24.04

# Avoid warnings by switching to noninteractive
ENV DEBIAN_FRONTEND=noninteractive

# # temporary fix for NVIDIA rotating public keys at the moment:
# # https://forums.developer.nvidia.com/t/invalid-public-key-for-cuda-apt-repository/212901/6
# RUN apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/3bf863cc.pub
# RUN apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu1804/x86_64/7fa2af80.pub

# This Dockerfile adds a non-root user with sudo access. Use the "remoteUser"
# property in devcontainer.json to use it. On Linux, the container user's GID/UIDs
# will be updated to match your local UID/GID (when using the dockerFile property).
# See https://aka.ms/vscode-remote/containers/non-root-user for details.
ARG USERNAME=aide
# required change of UID from 1000 for Ubuntu 24.04 and above
ARG USER_UID=1100
ARG USER_GID=$USER_UID

# Setup basic packages, environment and user
#TODO: switch ubuntugis ppa back to stable once 24.04 LTS (Jammy) release is out
RUN apt-get update && apt-get -y install software-properties-common python3 python-is-python3 python3-pip python3-launchpadlib python3-venv
RUN add-apt-repository -y ppa:ubuntugis/ubuntugis-unstable \
    && apt-get update \
    && apt-get -y install --no-install-recommends apt-utils dialog 2>&1 \
    #
    # Verify git, process tools, lsb-release (common in install instructions for CLIs) installed
    && apt-get -y install git openssh-client iproute2 procps iproute2 lsb-release libstdc++6 \
    #
    # TBC if all of this is required (from AIDE scripts)
    && apt-get -y install libpq-dev wget systemd \
    #
    # Libraries for OpenCV
    && apt-get -y install ffmpeg libsm6 libxext6 python3-opencv \
    #
    # GDAL
    && apt-get -y install gdal-bin libgdal-dev \
    #
    # Create a non-root user to use if preferred - see https://aka.ms/vscode-remote/containers/non-root-user.
    && groupadd --gid $USER_GID $USERNAME \
    && useradd -s /bin/bash --uid $USER_UID --gid $USER_GID -m $USERNAME \
    # [Optional] Add sudo support for the non-root user
    && apt-get install -y sudo \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME\
    && chmod 0440 /etc/sudoers.d/$USERNAME \
    #
    # Clean up
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# AIDE installation starts here
# specify the root folder where you wish to install AIDE
WORKDIR /home/$USERNAME/app

# create Python environment
ENV VIRTUAL_ENV=/opt/aide_env
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# install required libraries
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install torch torchvision
COPY requirements.txt docker/requirements.txt
RUN python3 -m pip install --no-build-isolation git+https://github.com/facebookresearch/detectron2.git
RUN python3 -m pip install -r docker/requirements.txt

# 2024/04/27: need to upgrade OpenSSL to avoid bug about "X509_V_FLAG_NOTIFY_POLICY"
RUN python3 -m pip install pyopenssl --upgrade

# ============================ DB SERVER ONLY BEGINS ======================================
# Setup PostgreSQL database
ENV LOC_REGION=Europe
ENV LOC_TIMEZONE=London
RUN ln -fs /usr/share/zoneinfo/$LOC_REGION/$LOC_TIMEZONE /etc/localtime \
    # specify postgres version you wish to use (must be >= 9.5)
    && version=12 \
    # install packages
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list \
    && wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add - \
    && apt-get update && sudo apt-get install -y postgresql-$version \
    && apt-get install -y postgis postgresql-${version}-postgis-scripts \
    # # update the postgres configuration with the correct port (NOTE: IT NEEDS TO MATCH THE settings.ini configuration !!!)
    # && sudo sed -i "s/\s*port\s*=\s[0-9]*/port = 17685/g" /etc/postgresql/$version/main/postgresql.conf \
    # modify authentication
    # NOTE: you might want to manually adapt these commands for increased security; the following makes postgres listen to all global connections
    
    && sudo sed -i "s/\s*#\s*listen_addresses\s=\s'localhost'/listen_addresses = '\*'/g" /etc/postgresql/$version/main/postgresql.conf \
    && echo "host    all             all             0.0.0.0/0               md5" | sudo tee -a /etc/postgresql/$version/main/pg_hba.conf > /dev/null 
    #&& sudo systemctl enable postgresql

# ============================ DB SERVER ONLY ENDS ======================================

# ============================ AI BACKEND BEGINS ========================================
# define RabbitMQ access credentials. NOTE: replace defaults with your own values
RUN sudo apt-get update && sudo apt-get install -y rabbitmq-server \
# optional: if the port for RabbitMQ is anything else than 5672, execute the following line:
    && port=5672   # replace with your port \
    && sudo sed -i "s/^\s*#\s*NODE_PORT\s*=.*/NODE_PORT=$port/g" /etc/rabbitmq/rabbitmq-env.conf 
    #&& sudo systemctl enable rabbitmq-server.service 

RUN sudo apt-get update && sudo apt-get -y install redis-server \
    # make sure Redis stores its messages in an accessible folder (we're using /var/lib/redis/aide.rdb here)
    && sudo sed -i "s/^\s*dir\s*.*/dir \/var\/lib\/redis/g" /etc/redis/redis.conf \
    && sudo sed -i "s/^\s*dbfilename\s*.*/dbfilename aide.rdb/g" /etc/redis/redis.conf \
    # also tell systemd
    && sudo mkdir -p /etc/systemd/system/redis.service.d \
    && echo -e "[Service]\nReadWriteDirectories=-/var/lib/redis" | sudo tee -a /etc/systemd/system/redis.service.d/override.conf > /dev/null \
    && sudo mkdir -p /var/lib/redis \
    && sudo chown -R redis:redis /var/lib/redis \
    # disable persistence. In general, we don't need Redis to save snapshots as it is only used as a result
    # (and therefore message) backend.
    && sudo sed -i "s/^\s*save/# save /g" /etc/redis/redis.conf \
    # optional: if the port is anything else than 6379, execute the following line:
    # replace with your port
    && port=6379 \
    && sudo sed -i "s/^\s*port\s*.*/port $port/g" /etc/redis/redis.conf \
    # ensure only ipv4 is bound (to work properly on Docker without changing it's configuration)
    && sudo sed -i "s/^\s*bind\s*.*/bind 127.0.0.1/g" /etc/redis/redis.conf 
    #&& sudo systemctl enable redis-server.service
# ============================ AI BACKEND ENDS ==========================================

# download AIDE source code (from local repository)
COPY . .
RUN chmod a+rx docker/container_init.sh && chmod a+rx AIDE.sh

# # Set to proper settings file
ENV PYTHONPATH=/home/${USERNAME}/app
ENV AIDE_CONFIG_PATH=/home/${USERNAME}/app/docker/settings.ini
ENV AIDE_MODULES=LabelUI,AIController,AIWorker,FileServer

CMD bash /home/aide/app/docker/container_init.sh \
    && bash AIDE.sh start

# Temporary command to prevent container from stopping if no command is privided
# CMD tail -f /dev/null
