# Upgrade from AIDE v1

If you already have an installation of the [first version](https://github.com/microsoft/aerial_wildlife_detection/tree/v1) (v1) of AIDE installed, you can upgrade it to the latest version (v3) as described below.

**Notes:**
* These instructions do not transfer a v1 project to a _new_ database, they just upgrade an existing v1 project to work with the v3 installation that points to the _same_ database.
* Once a v1 project has been successfully updated with this script, the original configuration .ini file can be discarded. There is no need to run this script more than one time for a specific v1 project.
* **Do NOT continue to use the v1 software on a project that has been upgraded to v3.**


To upgrade a project from v1 to v3, follow these steps:
1. Create a backup of your v1 `settings.ini` file somewhere.
2. Modify the new (v3) `config/settings.ini` file with the correct parameters.
   Notes:
    * Set a meaningful directory for the `staticfiles_dir` parameter under `[FileServer]`. AIDE v3 can host multiple projects, so it can be generic!
    * Any options specified in the v1 `settings.ini` file not present in the new version can be ignored. 
3. Move your v1 images to the right destination folder: `<staticfiles_dir>/<schema>`.
   For example:
    * If your v1 project's images reside in `/datadrive/v1/images` (parameter `staticfiles_dir` under `[FileServer]` of the v1 settings.ini file),
    * Your v1 project's database schema name is `my_great_project` (parameter `schema`under `[Database]` of the v1 settings.ini file),
    * You specify `/datadrive/v3/images` as the new folder for AIDE v3 (parameter `staticfiles_dir` under `[FileServer]` of the v3 settings.ini file),
    * Then you must move your images from `/datadrive/v1/images` to `/datadrive/v3/images/my_great_project`.
4. Clone the AIDE repository into a new folder:
`git clone https://github.com/bkellenb/AIDE.git`
5. Install missing dependencies in your environment
```bash
    conda activate aide
    pip install -y pyyaml
    $(python install/get_pytorch_version.py --format=conda --with-cuda=1)
    pip install git+https://github.com/facebookresearch/detectron2.git
    pip install -U -r requirements.txt
```
6. Set environment variables:
```bash
    export PYTHONPATH=.
    export AIDE_CONFIG_PATH=config/settings.ini
```
7. Run the following migration script (with the appropriate path at the end):
```bash
    python projectCreation/upgrade_v1_project.py --settings_filepath=/path/to/v1/settings.ini
```
If you did not do step 3, you might be asked if you want AIDE to create a symbolic link to your images. Be aware that although this works as a quick fix, it is not recommended for deployment, as other projects in AIDE v3 may be able to see each other's images this way, due to the recursive nature of the link.
7. Launch AIDE v3:
```bash
    ./AIDE.sh start
```
Unlike v1, this script always launches a Celery worker together with the Gunicorn server.