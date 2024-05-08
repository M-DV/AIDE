# Configuration of the settings INI file

The settings INI file is the primary project property access point for every AIDE module. It contains parameters, addresses and some passwords and must therefore never be exposed to the public!

The settings file is divided into the following categories:

## [Project]

In the latest version of AIDE, this section only contains the credentials for the so-called "super user" (who has full permission in every project).

| Name | Values | Default value | Required | Comments |
|---------------|-----------------|---------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| adminName | (string) |  | YES | Name of the AIDE administrator (super user) account. |
| adminEmail | (e-mail string) |  | YES | E-mail address of the AIDE administrator account. |
| adminPassword | (string) |  | YES | Plain text password of the AIDE administrator account. |



## [Server]

This section contains parameters for all the individual instances' addresses.

| Name | Values | Default value | Required | Comments |
|------------------|--------------------------|---------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| host | (IP address or hostname) | 0.0.0.0 | YES | This is the host IP address _of the current instance_. As such, it might need to be set differently for every machine taking part in AIDE. Be sure to change the individual addresses below to make the machines reachable to each other, whenever necessary. |
| port | (numeric) | 80 | YES | Network port _of the current instance_. Again, you might want to specify custom values depending on the machine here. For example, the frontend (_LabelUI_) might run on HTTP's standard port 80, but you can e.g. route the _AIWorker_ instances through different ports here.  Be sure to change the individual addresses below to make the machines reachable to each other, whenever necessary. |
| numWorkers | (numeric) | 6 | NO | Number of Gunicorn server threads to launch. More threads can serve more requests in parallel, but might also cause a computational overhead and use up more database connections.
| index_uri | (URI) | / |  | URL snippet under which the index page can be found. By default this can be left as "/", but may be changed if AIDE is e.g. deployed under a sub-URL, such as "http://www.mydomain.com/aide", in which case it would have to be changed to "/aide". |
| dataServer_uri | (URI) |  | YES | URI, resp. URL of the _FileServer_ instance. Note that the instance needs to be accessible to both the users accessing the _LabelUI_ webpage, as well as to any running _AIWorker_ instance.  In URL format this may include the port number **and** the _FileServer_'s "staticfiles_uri" parameter too (see below); for example: `http://fileserver.domain.com:67742/files`. |
| aiController_uri | (URI) |  |  | The same for the _AIController_ instance. This must primarily be accessible to running _AIWorker_ instances, but the value of it is also used in the frontend to determine whether AI support is enabled or not.  In URL format this may include the port number of the  _AIController_ too; for example:  `http://aicontroller.domain.com:67743`. |



## [UserHandler]

| Name | Values | Default value | Required | Comments |
|----------------------|---------------|---------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| time_login | numeric | 600 | NO |  Time (in seconds) for a session to last if the user is inactive. Upon exceeding the threshold specified here, the user is either asked to re-type their password, or else redirected to the index page. If set to a value <= 0 or unset, no login time restriction is applied. |
| create_account_token | (string) |  |  | A custom string of (preferably) random characters required to be known to users who would like to create a new account on the project page. This is to make the project semi-secret. If this value is set, the webpage to create a new account can be accessed as follows: `http://<hostname>/createAccount?t=<create_account_token>`, substituting the expressions in angular brackets accordingly. If left out, a new account can be created by simply visiting:  `http://<hostname>/createAccount`. |


## [LabelUI]

| Name | Values | Default value | Required | Comments |
|-|-|-|-|-|

| max_image_width | (numeric) | 2000 | NO | Maximum image width in pixels as
served to the frontend. Set to a reasonable value to accelerate data serving to Web clients and
  prevent Web browsers running out of memory. If provided, images will be resized so that their
  longer side matches its respective maximum value, with the images' aspect ratios preserved. Also
  applies to windows if image in project is split accordingly. Note that these settings only applies
  to the Web frontend, not to the AI models, nor does it modify image files themselves. Omit values
  or set either or both of them to value <= 0 to disable. | | max_image_height | (numeric) | 2000 |
NO | Ditto, for maximum image height. If neither value is provided or any of the values is <= 0,
image size will be unrestricted. If only one is provided, it will be copied over to the other. |


## [AIController]

| Name | Values | Default value | Required | Comments |
|-|-|-|-|-|
| broker_URL | (URL) | amqp://localhost | YES | URL under which the message broker (RabbitMQ, Redis, etc.) can be reached. This might include an access username, password, port and trailing specifier (e.g. queue). Refer to the individual frameworks for details. |
| result_backend | (URL) | redis://localhost:6379/0 | YES | Backend URL under which status updates and results are fetched. **Important:** it is required to use a persistent backend for the message store (do not use `rpc`). The recommended backend is [Redis](http://docs.celeryproject.org/en/latest/getting-started/brokers/redis.html). See details [here](#set-up-the-message-broker). |
| maxNumWorkers_train | (numeric) | -1 |  | Maximum number of AIWorker instances to consider when training. -1 means that all available AIWorkers will be involved in training, and that the images will be distributed evenly across them. If > 1 or = -1, the training images will be distributed evenly over the number of AIWorkers specified, and the model's 'average_model_states' function will be called once all workers have finished training to generate a new, holistic model state. Note that this might not always be preferred (some models might not allow to be averaged). In this case, set this number to 1 to limit training (on all training images) to just one AIWorker. |
| maxNumWorkers_inference | (numeric) | -1 |  | Maximum number of AIWorker instances to involve when doing inference on images. -1 means that all available AIWorkers will be involved, and that the images will be distributed evenly across them. |
| max_num_concurrent_tasks | (numeric) | 2 |  | Maximum number of tasks that can be launched at a time per project. Individual projects may provide their own override, but the value provided here serves as an absolute upper ceiling. Auto-launched tasks are always limited to one at a time; the number of tasks here takes these into account, even for user-launched tasks (i.e., if the number set here is 2 and there is already a task running, whether auto-launched or not, at most one additional task can be run at a time). Set to <= 0 to allow an unlimited number of tasks to be executed at a time per project. |


## [Mapserver]

| Name | Values | Default value | Required | Comments |
|----------------------------|--------------|---------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| wms_max_image_width | (numeric) | 2000 | NO | Maximum image width in pixels for WMS requests. If set to a numerical value > 0, WMS server will populate tag "MaxWidth" in GetCapabilities request. Note that this does not enforce restriction; a client could potentially ignore tag and request and receive larger images.
| wms_max_image_height | (numeric) | 2000 | NO | Maximum image height in pixels for WMS requests. If set to a numerical value > 0, WMS server will populate tag "MaxWidth" in GetCapabilities request. Note that this does not enforce restriction; a client could potentially ignore tag and request and receive larger images.


## [AIWorker]

| Name | Values | Default value | Required | Comments |
|----------------------------|--------------|---------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| inference_batch_size_limit | (numeric) | 128 | YES | Number of images to perform inference on at a time. If this value is smaller than the designated number of images for inference in a job, the total number of images will be split into chunks of this size and processed in order, on each AIWorker. This is especially important for data-intensive annotation types, such as segmentation masks, where all the annotations are loaded into system memory prior to calling the inference job. By limiting the number of images to be processed at once, pressure on system RAM can be relieved. Set to a reasonable value if you encounter out of memory issues on AIWorkers. If set to "-1", no limit in chunk size will be placed on inference (not recommended; this also means that one would have to wait a very long time to see predictions as they are only stored once inference has been completed). |



## [FileServer]

| Name | Values | Default value | Required | Comments |
|-|-|-|-|-|
| staticfiles_dir | (path) |  | YES | Root directory on the local disk of the file server to serve files from. |
| staticfiles_uri_addendum | (URI string) |  | NO | Optional snippet to append after the file server's host name. For example, if set to `aide`, the file server provides files through `http(s)://host:port/aide`. |
| tempfiles_dir | (path) | OS temp dir | NO | Directory where files like data download request results are stored. Defaults to a folder named "aide" in the OS' temporary files directory (i.e., `/tmp/aide` on Unix or Linux, `~/APPDATA/Local/Temp/aide` on Windows, or others). The temp folder will be automatically created during startup. Make sure the user accounts from which AIDE and the Celery processes are spawned have write access to this directory. |
| watch_folder_interval | (float) | 60 | NO | Interval (in seconds) for periodic project folder watch functionality. If project are configured to automatically watch their image folder for changes, those tasks will be carried out on the file server in a combined way every number of seconds specified here. Set to 0 (zero) or a negative value to globally disable folder watching for all projects. Default is 60 (one minute). |


## [Database]

| Name | Values | Default value | Required | Comments |
|---------------------|-----------|---------------|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| name | (string) |  | YES | Name of the Postgres database on the server. |
| schema | (string) |  | YES | Schema within the database to store the project data in. |
| host | (URL) |  | YES | URL under which the database can be accessed (without the port). Can be set to `localhost` if and only if all AIDE modules are to be launched on the same server the database is hosted on. |
| port | (numeric) |  | YES | Port the database listens to. Note: Postgres' default port is 5432; unless the database instance is solely connected to LAN (and not WAN), it is advised to change the Postgres port to another, free value. The [database installation instructions](setup_db.md) will automatically consider the custom port. |
| user | (string) |  | YES | Name of the user that is given access to the database. |
| password | (string) |  | YES | Password (in clear text) for the Postgres user. **NOTE:** unlike all other database fields, the password is case-sensitive. |
| credentials | (string) |  |  | Alternative form of providing database username and password through a text file, similar to credentials e.g. in Linux's fstab entries. Text file may contain lines like `username=user` and `password=pass`, without whitespaces. Parameters `user` and `password` that are directly provided in the .ini file have precedence over the credentials file. |
| max_num_connections | (numeric) | 16 |  | Maximum number of connections to the database per server running an AIDE module. This number, multiplied by the number of server instances running AIDE, must not exceed the maximum number of connections defined in Postgres' configuration file. A minimum number of 2 is required and will always be enforced at runtime. |