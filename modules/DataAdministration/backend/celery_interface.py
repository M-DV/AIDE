'''
    Wrapper for the Celery message broker concerning the data management module. This module may
    require some longer running tasks, such as the preparation of data to download, or the scanning
    of a directory for untracked images. These jobs are dispatched as Celery tasks. Function
    "init_celery_dispatcher" is to be initialized at launch time with a Celery app instance.

    2020-24 Benjamin Kellenberger
'''

import os
from celery import current_app

from modules.Database.app import Database
from util.configDef import Config
from .dataWorker import DataWorker


# initialize dataWorker
modules = os.environ['AIDE_MODULES']
config = Config()
worker = DataWorker(config, Database(config), passive_mode=True)

@current_app.task()
def aide_internal_notify(message):
    return worker.aide_internal_notify(message)


@current_app.task(name='DataAdministration.verify_images', rate_limit=1)
def verify_images(projects,
                  image_list=None,
                  quick_check=True):
    if image_list is None:
        image_list = []
    return worker.verifyImages(projects,
                               image_list,
                               quick_check)


@current_app.task(name='DataAdministration.list_images')
def list_images(project,
                folder=None,
                imageAddedRange=None,
                lastViewedRange=None,
                viewcountRange=None,
                numAnnoRange=None,
                numPredRange=None,
                orderBy=None,
                order='desc',
                startFrom=None,
                limit=None,
                offset=None):
    return worker.listImages(project,
                             folder,
                             imageAddedRange,
                             lastViewedRange,
                             viewcountRange,
                             numAnnoRange,
                             numPredRange,
                             orderBy,
                             order,
                             startFrom,
                             limit,
                             offset)


@current_app.task(name='DataAdministration.scan_for_images')
def scanForImages(project, skipIntegrityCheck=False):
    return worker.scanForImages(project, skipIntegrityCheck=skipIntegrityCheck)


@current_app.task(name='DataAdministration.add_existing_images')
def addExistingImages(project,
                      imageList=None,
                      skipIntegrityCheck=False,
                      createVirtualViews=False,
                      viewParameters=None):
    return worker.addExistingImages(project,
                                    imageList,
                                    skipIntegrityCheck=skipIntegrityCheck,
                                    createVirtualViews=createVirtualViews,
                                    viewParameters=viewParameters)

@current_app.task(name='DataAdministration.create_image_overviews')
def create_image_overviews(image_ids,
                            project,
                            scale_factors=(2,4,8,16),
                            method='nearest'):
    return worker.create_image_overviews(image_ids,
                                         project,
                                         scale_factors,
                                         method)

@current_app.task(name='DataAdministration.remove_images')
def removeImages(project,
                 imageList,
                 forceRemove=False,
                 deleteFromDisk=False):
    return worker.removeImages(project,
                               imageList,
                               forceRemove,
                               deleteFromDisk)

@current_app.task(name='DataAdministration.request_annotations')
def requestAnnotations(project,
                       username,
                       exportFormat,
                       dataType='annotation',
                       authorList=None,
                       dateRange=None,
                       ignoreImported=False,
                       parserArgs=None):
    if parserArgs is None:
        parserArgs = {}
    return worker.requestAnnotations(project,
                                     username,
                                     exportFormat,
                                     dataType,
                                     authorList,
                                     dateRange,
                                     ignoreImported,
                                     parserArgs)

# deprecated
@current_app.task(name='DataAdministration.prepare_data_download')
def prepareDataDownload(project, dataType='annotation', userList=None, dateRange=None, extraFields=None, segmaskFilenameOptions=None, segmaskEncoding='rgb'):
    return worker.prepareDataDownload(project, dataType, userList, dateRange, extraFields, segmaskFilenameOptions, segmaskEncoding)


@current_app.task(name='DataAdministration.watch_image_folders', rate_limit=1)
def watchImageFolders():
    return worker.watchImageFolders()


@current_app.task(name='DataAdministration.delete_project')
def deleteProject(project, deleteFiles=False):
    return worker.deleteProject(project, deleteFiles)
