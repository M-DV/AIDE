#!/bin/sh

# Launches a Celery consumer on the current machine.
# Requires pwd to be the root of the project and the correct Python
# env to be loaded.
#
# 2019-24 Benjamin Kellenberger

python_exec=$1
if [ ${#python_exec} = 0 ]; then
    python_exec=$(command -v python)
fi

launchCeleryBeat=false

IFS=',' read -ra ADDR <<< "$AIDE_MODULES"
for i in "${ADDR[@]}"; do
    module="$(echo "$i" | tr '[:upper:]' '[:lower:]')";
    if [ "$module" == "fileserver" ]; then
        folderWatchInterval=$($python_exec util/configDef.py --section=FileServer --parameter=watch_folder_interval --fallback=60);
        if [[ $folderWatchInterval -gt 0 ]]; then
            launchCeleryBeat=true;
        fi
    fi
done

if [ $launchCeleryBeat ]; then
    # folder watching interval specified; enable Celery beat
	tempDir="$($python_exec util/configDef.py --section=FileServer --parameter=tempfiles_dir --fallback=/tmp/aide)";
    temp_db=$tempDir/celerybeat_aide.db
    if [ -f $temp_db ]; then
        # remove old database entry to avoid compatibility issues with older versions
        rm $temp_db;
    fi
    mkdir -p $tempDir;
    $python_exec -m celery -A celery_worker worker -B -s $temp_db --hostname aide@%h
else
	$python_exec -m celery -A celery_worker worker --hostname aide@%h
fi