#!/bin/bash

# Launches or terminates AIDE with all the correct modules,
# including Celery, if required.
# The information on which modules and services to run come
# from the following two environment variables:
# * AIDE_CONFIG_PATH
# * AIDE_MODULES
# 
# 2020-24 Benjamin Kellenberger

python_exec=$3
if [ ${#python_exec} = 0 ]; then
    python_exec=$(command -v python)
fi

function start {

    IFS=',' read -ra ADDR <<< "$AIDE_MODULES"

    # Celery
    # launchCeleryBeat=false
    # IFS=',' read -ra ADDR <<< "$AIDE_MODULES"
    # for i in "${ADDR[@]}"; do
    #     module="$(echo "$i" | tr '[:upper:]' '[:lower:]')";
    #     if [ "$module" == "fileserver" ]; then
    #         folderWatchInterval=$($python_exec util/configDef.py --section=FileServer --parameter=watch_folder_interval --fallback=60);
    #         if [ $folderWatchInterval -gt 0 ]; then
    #             launchCeleryBeat=true;
    #         fi
    #     fi
    # done
    # if [ $launchCeleryBeat ]; then
    #     # folder watching interval specified; enable Celery beat
    #     tempDir="$($python_exec util/configDef.py --section=FileServer --parameter=tempfiles_dir --fallback=/tmp/aide/celery)";
    #     mkdir -p $tempDir;
    #     $python_exec -m celery -A celery_worker worker -B -s $tempDir --hostname aide@%h &
    # else
    #     $python_exec -m celery -A celery_worker worker --hostname aide@%h & 
    # fi
    source AIDE_worker.sh $python_exec &

    # AIDE
    numHTTPmodules=0;
    for i in "${ADDR[@]}"; do
        module="$(echo "$i" | tr '[:upper:]' '[:lower:]')";
        if [ "$module" != "aiworker" ]; then
            ((numHTTPmodules++));
        fi
    done

    if [ $numHTTPmodules -gt 0 ]; then
        # perform verbose pre-flight checks
        $python_exec setup/assemble_server.py --migrate_db 1

        if [ $? -eq 0 ]; then
            # pre-flight checks succeeded; get host and port from configuration file
            host=$($python_exec util/configDef.py --section=Server --parameter=host)
            port=$($python_exec util/configDef.py --section=Server --parameter=port)
            numWorkers=$($python_exec util/configDef.py --section=Server --parameter=numWorkers --type=int --fallback=6)

            debug="$(echo "$2" | tr '[:upper:]' '[:lower:]')";
            if [ "$debug" == "debug" ]; then
                debug="--log-level debug";
            else
                debug="";
            fi
            $python_exec -m gunicorn application:app --bind=$host:$port --workers=$numWorkers $debug
        else
            echo -e "\033[0;31mPre-flight checks failed; aborting launch of AIDE.\033[0m"
        fi
    else
        echo "Machine only runs as an AIWorker; skipping set up of HTTP web server..."
    fi
}

function stop {
    $python_exec -m celery -A celery_worker purge -f;
    $python_exec -m celery -A celery_worker control shutdown;
    pkill -f "celery_worker";
    pkill -f gunicorn;
}

function restart {
    stop;
    start;
}

mode=$1;

if [ "$mode" == "start" ]; then
    start;
elif [ "$mode" == "restart" ]; then
    restart;
elif [ "$mode" == "stop" ]; then
    stop;
else
    echo "Usage: AIDE.sh {start|restart|stop} [debug] [python_exec]"
fi