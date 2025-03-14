'''
    Middleware layer for the data administration module. Responsible for the following tasks and
    operations:

        - image management: upload and deletion to and from disk
        - annotation and prediction management: up- and download of annotations and model
          predictions

    2020-24 Benjamin Kellenberger
'''

import html
from psycopg2 import sql

from util.parsers import PARSERS
from . import celery_interface
from .dataWorker import DataWorker


class DataAdministrationMiddleware:

    def __init__(self, config, dbConnector, taskCoordinator):
        self.config = config
        self.dbConnector = dbConnector
        self.taskCoordinator = taskCoordinator
        self.dataWorker = DataWorker(config, dbConnector)

        self.jobs = {}      # dict per project of jobs



    def _submit_task(self, project, username, process):
        return self.taskCoordinator.submit_task(project, username, process, 'FileServer')



    def poll_task_status(self, project, task_id):
        return self.taskCoordinator.poll_task_status(project, task_id)



    def verify_images(self, project, username, image_list=[], quick_check=False):
        '''
            Launches a Celery task to verify the images listed in a database for
            integrity.
        '''
        # submit task
        process = celery_interface.verify_images.si(project, image_list, quick_check)
        task_id = self._submit_task(project, username, process)
        return task_id



    def getImageFolders(self, project):
        '''
            Returns a dict representing a hierarchical directory tree under which the images are
            stored for a specific project.
        '''

        def _integrate_branch(tree, members):
            if len(members) == 0:
                return tree
            if members[0] not in tree:
                tree[members[0]] = {}
            if len(members)>1:
                tree[members[0]] = _integrate_branch(tree[members[0]], members[1:])
            return tree

        tree = {}
        folder_names = self.dbConnector.execute(sql.SQL('''
            SELECT folder FROM {}
            ORDER BY folder ASC;
        ''').format(
            sql.Identifier(html.escape(project), 'filehierarchy')
        ), None, 'all')
        if folder_names is not None and len(folder_names):
            for folder_name in folder_names:
                folder = folder_name['folder']
                if folder is None or len(folder) == 0:
                    continue
                parents = folder.strip('/').split('/')
                tree = _integrate_branch(tree, parents)
        return tree



    def listImages(self, project, username, folder=None, tags=None, imageAddedRange=None, lastViewedRange=None,
            viewcountRange=None, numAnnoRange=None, numPredRange=None,
            orderBy=None, order='desc', startFrom=None, limit=None, offset=None):
        '''
            #TODO: update description
            Returns a list of images, with ID, filename,
            date image was added, viewcount, number of annotations,
            number of predictions, and last time viewed, for a given
            project.
            The list can be filtered by all those properties (e.g. 
            date and time image was added, last checked; number of
            annotations, etc.), as well as limited in length (images
            are sorted by date_added).
        '''
        # submit job
        process = celery_interface.list_images.si(project, folder, tags, imageAddedRange,
                                                lastViewedRange, viewcountRange,
                                                numAnnoRange, numPredRange,
                                                orderBy, order, startFrom,
                                                limit, offset)

        task_id = self._submit_task(project, username, process)
        return task_id



    def create_upload_session(self,
                              project: str,
                              user: str,
                              session_kwargs: dict) -> str:
        '''
            Creates a new session of image and/or label files upload.
            Receives metadata regarding the upload (whether to import
            images, annotations; parameters; number of expected files) and
            creates a new session id. Then, the session's metadata gets
            stored in the "<temp folder>/aide_admin/<project>/<session id>"
            directory in a JSON file.

            The idea behind sessions is to inform the server about the
            expected number of files to be uploaded. Basically, we want to
            only parse annotations once every single file has been uploaded
            and parsed, to make sure we have no data loss.

            Returns the session ID as a response.
        '''
        return self.dataWorker.create_upload_session(project,
                                                     user,
                                                     session_kwargs)



    def verifySessionAccess(self, project, user, sessionID):
        '''
            Returns True if a user has access to a given upload session ID
            (i.e., they initiated it) and False if not or if the session with
            given ID does not exist.
        '''
        return self.dataWorker.verifySessionAccess(project, user, sessionID)



    def uploadData(self, project, username, sessionID, files):
        '''
            Receives "files" (a Bottle.py files object) and uploads them to the
            FileServer under a given "sessionID". If the session ID does not
            exist or else the user has no access to it, an Exception is raised.

            Otherwise, the raw files are uploaded to the temporary directory on
            the FileServer as specified in the session's metadata. Depending on
            the flags set in the metadata, the images are uploaded, converted,
            split, etc. Upon completion (i.e., upload of the expected number of
            images as per session metadata), and if the user specified to (also)
            upload images, an extra Celery task is invoked that parses the
            uploaded files and tries to import annotations accordingly.
        '''
        return self.dataWorker.uploadData(project, username, sessionID, files)



    def scanForImages(self, project, username, skipIntegrityCheck=False):
        '''
            #TODO: update description
            Searches the project image folder on disk for
            files that are valid, but have not (yet) been added
            to the database.
            Returns a list of paths with files.
        '''

        # submit job
        process = celery_interface.scanForImages.si(project, skipIntegrityCheck)

        task_id = self._submit_task(project, username, process)
        return task_id



    def addExistingImages(self, project, username, imageList=None, skipIntegrityCheck=False,
        createVirtualViews=False, viewParameters=None):
        '''
            #TODO: update description
            Scans the project folder on the file system
            for images that are physically saved, but not
            (yet) added to the database.
            Adds them to the project's database schema.
            If an imageList iterable is provided, only
            the intersection between identified images on
            disk and in the iterable are added.
            If imageList is a string with contents 'all', all
            untracked images on disk will be added.

            Returns a list of image IDs and file names that
            were eventually added to the project database schema.
        '''
        # submit job
        process = celery_interface.addExistingImages.si(project, imageList, skipIntegrityCheck,
                                                        createVirtualViews, viewParameters)

        task_id = self._submit_task(project, username, process)
        return task_id


    def create_image_overviews(self,
                                project,
                                username,
                                image_ids,
                                scale_factors=(2,4,8,16),
                                method='nearest'):
        '''
            Launches a Celery task to create image overviews (image pyramids) for geospatial images.
            Project must have a spatial reference (SRID) defined; otherwise the method returns
            without any changes.
        '''
        # submit job
        process = celery_interface.create_image_overviews.si(image_ids,
                                                            project,
                                                            scale_factors,
                                                            method)

        task_id = self._submit_task(project, username, process)
        return task_id

    
    def removeImages(self, project, username, imageList, forceRemove=False, deleteFromDisk=False):
        '''
            #TODO: update description
            Receives an iterable of image IDs and removes them
            from the project database schema, including associated
            user views, annotations, and predictions made.
            Only removes entries if no user views, annotations, and
            predictions exist, or else if "forceRemove" is True.
            If "deleteFromDisk" is True, the image files are also
            deleted from the project directory on the file system.

            Returns a list of images that were deleted.
        '''

        # submit job
        process = celery_interface.removeImages.si(project,
                                                    imageList,
                                                    forceRemove,
                                                    deleteFromDisk)

        task_id = self._submit_task(project, username, process)
        return task_id

    

    def getParserInfo(self, project=None, method='import'):
        '''
            Assembles all available parsers of annotation/prediction formats
            along with their HTML markup for custom options, if available. If a
            project shortname is provided, parsers are filtered w.r.t. the
            project's annotation and prediction types.
        '''
        # get annotation and prediction types if project provided
        if project is not None:
            query = self.dbConnector.execute('''
                SELECT annotationType, predictionType
                FROM "aide_admin".project
                WHERE shortname = %s;
            ''', (project,), 1)
            annoType = (query[0]['annotationtype'],)
            predType = (query[0]['predictiontype'],)
        else:
            annoType, predType = PARSERS.keys(), PARSERS.keys()

        info = {
            'annotation': {},
            'prediction': {}
        }

        # get HTML options for each parser
        for at in annoType:
            for annoFormat in PARSERS[at].keys():
                # we're at parser class level here
                info['annotation'][annoFormat] = {
                    'name': PARSERS[at][annoFormat].NAME,
                    'info': PARSERS[at][annoFormat].INFO,
                    'options': PARSERS[at][annoFormat].get_html_options(method)
                }
        for pt in predType:
            for annoFormat in PARSERS[pt].keys():
                # we're at parser class level here
                info['prediction'][annoFormat] = {
                    'name': PARSERS[pt][annoFormat].NAME,
                    'info': PARSERS[pt][annoFormat].INFO,
                    'options': PARSERS[pt][annoFormat].get_html_options(method)
                }
        return info


    def requestAnnotations(self, project, username, exportFormat, dataType='annotation', authorList=None, dateRange=None, ignoreImported=True, parserArgs={}):
        '''
            Launches a Celery task that polls the database for project data
            according to the options provided, and then initializes a parser
            that exports annotations (or predictions) to a Zipfile on disk. The
            task then returns the path to that Zipfile once completed.
        '''
        # #TODO: for debugging
        # celery_interface.requestAnnotations(project,
        #                                             username,
        #                                             exportFormat,
        #                                             dataType,
        #                                             authorList,
        #                                             dateRange,
        #                                             ignoreImported,
        #                                             parserArgs)

        # submit task
        process = celery_interface.requestAnnotations.si(project,
                                                    username,
                                                    exportFormat,
                                                    dataType,
                                                    authorList,
                                                    dateRange,
                                                    ignoreImported,
                                                    parserArgs)

        task_id = self._submit_task(project, username, process)
        return task_id


    # deprecated
    def prepareDataDownload(self, project, username, dataType='annotation', userList=None, dateRange=None, extraFields=None, segmaskFilenameOptions=None, segmaskEncoding='rgb'):
        '''
            #TODO: update description
            Polls the database for project data according to the
            specified restrictions:
            - dataType: "annotation" or "prediction"
            - userList: for type "annotation": None (all users) or
                        an iterable of user names
            - dateRange: None (all dates) or two values for a mini-
                         mum and maximum timestamp
            - extraFields: additional DB relation columns to query, such as the
                           browser metadata / user agent. To be supplied as a dict.
                           If None, no extra fields will be queried.
            - segmaskFilenameOptions: for segmentation masks only: None (defaults)
                                      or a dict of fields 'baseName' ("id" or "filename"),
                                      'prefix' (str) and 'suffix' (str) to customize the
                                      segmentation masks' file names.
            - segmaskEncoding: for segmentation masks only: set to 'rgb'
                               to encode pixel values with red-green-blue,
                               or to 'indexed' to assign label class index
                               to pixels.
            
            Creates a file in this machine's temporary directory
            and returns the file name to it.
            Note that in some cases (esp. for semantic segmentation),
            the number of queryable entries may be limited due to
            file size and free disk space restrictions. An upper cei-
            ling is specified in the configuration *.ini file ('TODO')
        '''
        # submit job
        process = celery_interface.prepareDataDownload.si(project,
                                                    dataType,
                                                    userList,
                                                    dateRange,
                                                    extraFields,
                                                    segmaskFilenameOptions,
                                                    segmaskEncoding)

        task_id = self._submit_task(project, username, process)
        return task_id