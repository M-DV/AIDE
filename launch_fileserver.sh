#!/bin/bash

# Convenience function to run a FileServer instance. Requires pwd to be the root of the project and
# the correct Python env to be loaded.
#
# 2019-24 Benjamin Kellenberger

# modules to run
export AIDE_MODULES=FileServer

# pre-flight checks
python setup/assemble_server.py

if [ $? -eq 0 ]; then
    # pre-flight checks succeeded; get host and port from configuration file
    host=$(python util/configDef.py --section=Server --parameter=host)
    port=$(python util/configDef.py --section=Server --parameter=port)
    numWorkers=$(python util/configDef.py --section=Server --parameter=numWorkers --fallback=6)
    gunicorn application:app --bind=$host:$port --workers=$numWorkers
else
    echo -e "\033[0;31mPre-flight checks failed; aborting launch of AIDE.\033[0m"
fi