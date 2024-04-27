# Main entry point to run AIDE in Docker on CPU machines (without CUDA).
#
# 2020-24 Jaroslaw Szczegielniak, Benjamin Kellenberger

docker volume ls | grep -q aide_images || docker volume create aide_images
docker volume ls | grep -q aide_db_data || docker volume create aide_db_data

docker run --name aide_cnt \
 --rm \
 -v `pwd`:/home/aide/app \
 -v aide_db_data:/var/lib/postgresql/12/main \
 -v aide_images:/home/aide/images \
 -p 8080:8080 \
 -h 'aide_app_host' \
 aide_app

 # Options:
 # --name   - container name
 # --gpus   - sets GPU configuration
 # --rm     - forces container removal on close (it doesn't affect volumes)
 # -v       - maps volume (note: aide_db_data and aide_images needs to be created before this script is executed)
 # -p       - maps ports
 # -h       - sets hostname (fixed hostname is required for some internal components)
