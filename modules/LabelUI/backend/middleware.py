'''
    Definition of the layer between the UI frontend and the database.

    2019-24 Benjamin Kellenberger
'''

import os
from typing import Iterable
from uuid import UUID
from datetime import datetime
import json
import pytz
import dateutil.parser
from PIL import Image
from psycopg2 import sql
from util import helpers, common
from .sql_string_builder import SQLStringBuilder
from .annotation_sql_tokens import QueryStrings_annotation, AnnotationParser


class DBMiddleware():
    '''
        Label UI middleware, performing communication between frontend and the database.
    '''
    def __init__(self, config, dbConnector):
        self.config = config
        self.dbConnector = dbConnector

        # project settings that cannot be changed (project shorthand -> {settings})
        self.project_immutables = {}

        self._fetchProjectSettings()
        self.sqlBuilder = SQLStringBuilder()
        self.annoParser = AnnotationParser()


    def _fetchProjectSettings(self):
        # AI controller URI
        aiControllerURI = self.config.get_property('Server', 'aiController_uri')
        if aiControllerURI is None or aiControllerURI.strip() == '':
            # no AI backend configured
            aiControllerURI = None

        # global, project-independent settings
        self.globalSettings = {
            'indexURI': self.config.get_property('Server',
                                                 'index_uri',
                                                 dtype=str,
                                                 fallback='/'),
            'dataServerURI': self.config.get_property('Server', 'dataServer_uri'),
            'aiControllerURI': aiControllerURI
        }

        # default styles
        try:
            # check if custom default styles are provided
            with open('config/default_ui_settings.json', 'r', encoding='utf-8') as f_styles:
                self.defaultStyles = json.load(f_styles)
        except Exception:
            # resort to built-in styles
            with open('modules/ProjectAdministration/static/json/default_ui_settings.json',
                      'r',
                      encoding='utf-8') as f_default:
                self.defaultStyles = json.load(f_default)


    def _assemble_annotations(self,
                              project: str,
                              queryData: list,
                              hideGoldenQuestionInfo: bool) -> dict:
        response = {}
        for row in queryData:
            img_id = str(row['image'])
            if img_id not in response:
                response[img_id] = {
                    'fileName': row['filename'],
                    'w_x': row.get('w_x', None),
                    'w_y': row.get('w_y', None),
                    'w_width': row.get('w_width', None),
                    'w_height': row.get('w_height', None),
                    'predictions': {},
                    'annotations': {},
                    'last_checked': None
                }
            viewcount = row['viewcount']
            if viewcount is not None:
                response[img_id]['viewcount'] = viewcount
            last_checked = row['last_checked']
            if last_checked is not None:
                if response[img_id]['last_checked'] is None:
                    response[img_id]['last_checked'] = last_checked
                else:
                    response[img_id]['last_checked'] = max(response[img_id]['last_checked'],
                                                           last_checked)

            if not hideGoldenQuestionInfo:
                response[img_id]['isGoldenQuestion'] = row['isgoldenquestion']

            response[img_id]['isBookmarked'] = row['isbookmarked']

            # parse annotations and predictions
            entry_id = str(row['id'])
            if row['ctype'] is not None:
                colnames = self.sqlBuilder.getColnames(
                    self.project_immutables[project]['annotationType'],
                    self.project_immutables[project]['predictionType'],
                    row['ctype'])
                entry = {}
                for c in colnames:
                    value = row[c]
                    if isinstance(value, datetime):
                        value = value.timestamp()
                    elif isinstance(value, UUID):
                        value = str(value)
                    entry[c] = value

                if row['ctype'] == 'annotation':
                    response[img_id]['annotations'][entry_id] = entry
                elif row['ctype'] == 'prediction':
                    response[img_id]['predictions'][entry_id] = entry

        return response


    def _set_images_requested(self,
                              project: str,
                              imageIDs: Iterable) -> None:
        '''
            Sets column "last_requested" of relation "image"
            to the current date. This is done during image
            querying to signal that an image has been requested,
            but not (yet) viewed.
        '''
        # prepare insertion values
        now = datetime.now(tz=pytz.utc)
        vals = []
        for key in imageIDs:
            vals.append(key)
        if len(vals) > 0:
            query_str = sql.SQL('''
                UPDATE {id_img}
                SET last_requested = %s
                WHERE id IN %s;
            ''').format(id_img=sql.Identifier(project, 'image'))
            self.dbConnector.execute(query_str, (now, tuple(vals),), None)


    def _get_sample_metadata(self,
                             metaType: str) -> dict:
        '''
            Returns a dummy annotation or prediction for the sample
            image in the "exampleData" folder, depending on the "metaType"
            specified (i.e., labels, points, boundingBoxes, or segmentationMasks).
        '''
        if metaType == 'labels':
            return {
                'id': '00000000-0000-0000-0000-000000000000',
                'label': '00000000-0000-0000-0000-000000000000',
                'confidence': 1.0,
                'priority': 1.0,
                'viewcount': None
            }
        if metaType in ('points', 'boundingBoxes'):
            return {
                'id': '00000000-0000-0000-0000-000000000000',
                'label': '00000000-0000-0000-0000-000000000000',
                'x': 0.542959427207637,
                'y': 0.5322069489713102,
                'width': 0.6133651551312653,
                'height': 0.7407598263401316,
                'confidence': 1.0,
                'priority': 1.0,
                'viewcount': None
            }
        if metaType == 'polygons':
            with open('modules/LabelUI/static/exampleData/sample_polygon.json',
                      'r',
                      encoding='utf-8') as f_polygon:
                return json.load(f_polygon)
        if metaType == 'segmentationMasks':
            # read segmentation mask from disk
            segmask = Image.open('modules/LabelUI/static/exampleData/sample_segmentationMask.tif')
            segmask, width, height = helpers.imageToBase64(segmask)
            return {
                'id': '00000000-0000-0000-0000-000000000000',
                'width': width,
                'height': height,
                'segmentationmask': segmask,
                'confidence': 1.0,
                'priority': 1.0,
                'viewcount': None
            }
        return {}


    def get_project_immutables(self,
                               project: str) -> dict:
        '''
            Returns project properties that are immutable (currently: the project's annotation and
            prediction types). Caches values for reduced database access in future.

            Args:
                - "project": str, project shortname

            Returns:
                dict, the project's immutable properties
        '''
        if self.project_immutables.get(project, {}) is None:
            return None
        if project not in self.project_immutables:
            anno_type, pred_type = common.get_project_immutables(project, self.dbConnector)
            if anno_type is None or pred_type is None:
                self.project_immutables[project] = None
                return None
            self.project_immutables[project] = {
                'annotationType': anno_type,
                'predictionType': pred_type
            }
        return self.project_immutables[project]


    def get_project_ui_settings(self,
                                project: str) -> dict:
        '''
            Returns the project's user interface settings).

            Args:
                - "project": str, project shortname

            Returns:
                dict, the project's UI settings
        '''
        query_str = 'SELECT ui_settings FROM aide_admin.project WHERE shortname = %s;'
        result = self.dbConnector.execute(query_str, (project,), 1)
        result = json.loads(result[0]['ui_settings'])

        # complete styles with defaults where necessary
        # (may be required for project that got upgraded from v1)
        result = helpers.check_args(result, self.defaultStyles)

        return result


    def getProjectSettings(self,
                           project: str) -> dict:
        '''
            Queries the database for general project-specific metadata, such as:
            - Classes: names, indices, default colors
            - Annotation type: one of {class labels, positions, bboxes}
        '''
        # publicly available info from DB
        proj_settings = self.getProjectInfo(project)

        # label classes
        proj_settings['classes'] = self.getClassDefinitions(project)

        # static and dynamic project settings and properties from configuration file
        proj_settings = {**proj_settings,
                         **self.get_project_immutables(project),
                         **self.get_project_ui_settings(project),
                         **self.globalSettings}

        # append project shorthand to AIController URI 
        if 'aiControllerURI' in proj_settings and \
            proj_settings['aiControllerURI'] is not None and \
                len(proj_settings['aiControllerURI']) > 0:
            proj_settings['aiControllerURI'] = os.path.join(proj_settings['aiControllerURI'],
                                                            project) + '/'

        return proj_settings


    def getProjectInfo(self,
                       project: str) -> dict:
        '''
            Returns safe, shareable information about the project
            (i.e., users don't need to be part of the project to see these data).
        '''
        query_str = '''
            SELECT shortname, name, description, demoMode,
            interface_enabled, archived, ai_model_enabled,
            ai_model_library, ai_alcriterion_library,
            segmentation_ignore_unlabeled
            FROM aide_admin.project
            WHERE shortname = %s
        '''
        result = self.dbConnector.execute(query_str, (project,), 1)[0]

        # provide flag if AI model is available
        ai_models_available = all([
            result['ai_model_library'] is not None and len(result['ai_model_library']),
            result['ai_alcriterion_library'] is not None and len(result['ai_alcriterion_library'])
        ])
        ai_model_autotraining_enabled = (ai_models_available and result['ai_model_enabled'])

        return {
            'projectShortname': result['shortname'],
            'projectName': result['name'],
            'projectDescription': result['description'],
            'demoMode': result['demomode'],
            'interface_enabled': result['interface_enabled'] and not result['archived'],
            'ai_model_available': ai_models_available,
            'ai_model_autotraining_enabled': ai_model_autotraining_enabled,
            'segmentation_ignore_unlabeled': result['segmentation_ignore_unlabeled']
        }


    def getClassDefinitions(self,
                            project: str,
                            showHidden: bool=False) -> dict:
        '''
            Returns a dictionary with entries for all classes in the project.
        '''

        # query data
        query_str = sql.SQL('''
            SELECT 'group' AS type, id, NULL as idx, name, color, parent, NULL AS keystroke,
                    NULL AS hidden FROM {}
            UNION ALL
            SELECT 'class' AS type, id, idx, name, color, labelclassgroup, keystroke, hidden FROM {}
            {};
            ''').format(
                sql.Identifier(project, 'labelclassgroup'),
                sql.Identifier(project, 'labelclass'),
                sql.SQL('' if showHidden else 'WHERE hidden IS false')
            )

        class_data = self.dbConnector.execute(query_str, None, 'all')

        # assemble entries first
        all_entries = {}
        num_classes = 0
        if class_data is not None:
            for cl in class_data:
                class_id = str(cl['id'])
                entry = {
                    'id': class_id,
                    'name': cl['name'],
                    'color': cl['color'],
                    'parent': str(cl['parent']) if cl['parent'] is not None else None,
                    'hidden': cl['hidden']
                }
                if cl['type'] == 'group':
                    entry['entries'] = {}
                else:
                    entry['index'] = cl['idx']
                    entry['keystroke'] = cl['keystroke']
                    num_classes += 1
                all_entries[class_id] = entry

        # transform into tree
        def _find_parent(tree, tree_parent_id):
            if tree_parent_id is None:
                return None
            if tree.get('id', None) == tree_parent_id:
                return tree
            for ek in tree.get('entries', {}).keys():
                rv = _find_parent(tree['entries'][ek], tree_parent_id)
                if rv is not None:
                    return rv
                return None
            return None


        all_entries = {
            'entries': all_entries
        }
        for key in list(all_entries['entries'].keys()):
            entry = all_entries['entries'][key]
            parent_id = entry['parent']
            del entry['parent']

            if parent_id is None:
                # entry or group with no parent: append to root directly
                all_entries['entries'][key] = entry

            else:
                # move item
                parent = _find_parent(all_entries, parent_id)
                parent['entries'][key] = entry
                del all_entries['entries'][key]

        all_entries['numClasses'] = num_classes
        return all_entries


    def getBatch_fixed(self, project, username, data, hideGoldenQuestionInfo=True):
        '''
            Returns entries from the database based on the list of data entry identifiers specified.
        '''

        if not len(data):
            return { 'entries': {} }

        # query
        projImmutables = self.get_project_immutables(project)
        demoMode = common.check_demo_mode(project, self.dbConnector)
        queryStr = self.sqlBuilder.getFixedImagesQueryString(project, projImmutables['annotationType'], projImmutables['predictionType'], demoMode)

        # verify provided UUIDs
        uuids = []
        imgs_malformed = []
        for d in data:
            try:
                uuids.append(UUID(d))
            except Exception:
                imgs_malformed.append(d)
        uuids = tuple(uuids)

        if not len(uuids):
            return {
                'entries': {},
                'imgs_malformed': imgs_malformed
            }

        # parse results
        if demoMode:
            queryVals = (uuids,)
        else:
            queryVals = (uuids, username, username,)

        annoResult = self.dbConnector.execute(queryStr, queryVals, 'all')
        try:
            response = self._assemble_annotations(project, annoResult, hideGoldenQuestionInfo)
        except Exception as e:
            print(e)
    
        # filter out images that are invalid
        imgs_malformed = list(set(imgs_malformed).union(set(data).difference(set(response.keys()))))

        # mark images as requested
        self._set_images_requested(project, response)

        response = {
            'entries': response
        }
        if len(imgs_malformed):
            response['imgs_malformed'] = imgs_malformed

        return response
        

    def getBatch_auto(self, project, username, order='unlabeled', subset='default', limit=None, hideGoldenQuestionInfo=True):
        '''
            TODO: description
        '''
        # query
        projImmutables = self.get_project_immutables(project)
        demoMode = common.check_demo_mode(project, self.dbConnector)
        queryStr = self.sqlBuilder.getNextBatchQueryString(project, projImmutables['annotationType'], projImmutables['predictionType'], order, subset, demoMode)

        # limit (TODO: make 128 a hyperparameter)
        if limit is None:
            limit = 128
        else:
            limit = min(int(limit), 128)

        # parse results
        queryVals = (username,username,limit,username,)
        if demoMode:
            queryVals = (limit,)

        annoResult = self.dbConnector.execute(queryStr, queryVals, 'all')
        try:
            response = self._assemble_annotations(project, annoResult, hideGoldenQuestionInfo)
            
            # mark images as requested
            self._set_images_requested(project, response)
        except Exception as e:
            print(e)
            return { 'entries': {}}

        return { 'entries': response }


    def getBatch_timeRange(self, project, minTimestamp, maxTimestamp, userList, skipEmptyImages=False, limit=None, goldenQuestionsOnly=False, hideGoldenQuestionInfo=True, lastImageUUID=None):
        '''
            Returns images that have been annotated within the given time range and/or
            by the given user(s). All arguments are optional.
            Useful for reviewing existing annotations.
        '''
        # query string
        projImmutables = self.get_project_immutables(project)
        if isinstance(lastImageUUID, str):
            lastImageUUID = UUID(lastImageUUID)
        queryStr = self.sqlBuilder.getDateQueryString(project, projImmutables['annotationType'], minTimestamp, maxTimestamp, userList, skipEmptyImages, goldenQuestionsOnly, lastImageUUID)

        # check validity and provide arguments
        queryVals = []
        if userList is not None:
            queryVals.append(tuple(userList))
        if minTimestamp is not None:
            queryVals.append(minTimestamp)
        if maxTimestamp is not None:
            queryVals.append(maxTimestamp)
        if lastImageUUID is not None:
            queryVals.append(lastImageUUID)
        if skipEmptyImages and userList is not None:
            queryVals.append(tuple(userList))

        # limit (TODO: make 128 a hyperparameter)
        if limit is None:
            limit = 128
        else:
            limit = min(int(limit), 128)
        queryVals.append(limit)

        if userList is not None:
            queryVals.append(tuple(userList))

        # query and parse results
        annoResult = self.dbConnector.execute(queryStr, tuple(queryVals), 'all')
        try:
            response = self._assemble_annotations(project, annoResult, hideGoldenQuestionInfo)
        except Exception as e:
            print(e)

        # # mark images as requested
        # self._set_images_requested(project, response)


        return { 'entries': response }

    
    def get_timeRange(self, project, userList, skipEmptyImages=False, goldenQuestionsOnly=False):
        '''
            Returns two timestamps denoting the temporal limits within which
            images have been viewed by the users provided in the userList.
            Arguments:
            - userList: string (single user name) or list of strings (multiple).
                        Can also be None; in this case all annotations will be
                        checked.
            - skipEmptyImages: if True, only images that contain at least one
                               annotation will be considered.
            - goldenQuestionsOnly: if True, only images flagged as golden questions
                                   will be shown.
        '''
        # query string
        queryStr = self.sqlBuilder.getTimeRangeQueryString(project, userList, skipEmptyImages, goldenQuestionsOnly)

        arguments = (None if userList is None else tuple(userList))
        result = self.dbConnector.execute(queryStr, (arguments,), numReturn=1)

        if result is not None and len(result):
            return {
                'minTimestamp': result[0]['mintimestamp'],
                'maxTimestamp': result[0]['maxtimestamp'],
            }
        else:
            return {
                'error': 'no annotations made'
            }


    def get_sampleData(self, project):
        '''
            Returns a sample image from the project, with annotations
            (from one of the admins) and predictions.
            If no image, no annotations, and/or no predictions are
            available, a built-in default is returned instead.
        '''
        projImmutables = self.get_project_immutables(project)
        queryStr = self.sqlBuilder.getSampleDataQueryString(project, projImmutables['annotationType'], projImmutables['predictionType'])

        # query and parse results
        response = None
        annoResult = self.dbConnector.execute(queryStr, None, 'all')
        try:
            response = self._assemble_annotations(project, annoResult, True)
        except Exception as e:
            print(e)
        
        if response is None or not len(response):
            # no valid data found for project; fall back to sample data
            response = {
                '00000000-0000-0000-0000-000000000000': {
                    'fileName': '/static/interface/exampleData/sample_image.jpg',
                    'viewcount': 1,
                    'annotations': {
                        '00000000-0000-0000-0000-000000000000': self._get_sample_metadata(projImmutables['annotationType'])
                    },
                    'predictions': {
                        '00000000-0000-0000-0000-000000000000': self._get_sample_metadata(projImmutables['predictionType'])
                    },
                    'last_checked': None,
                    'isGoldenQuestion': True
                }
            }
        return response



    def submitAnnotations(self, project, username, submissions):
        '''
            Sends user-provided annotations to the database.
        '''
        if common.check_demo_mode(project, self.dbConnector):
            return 1

        projImmutables = self.get_project_immutables(project)

        # assemble values
        colnames = getattr(QueryStrings_annotation, projImmutables['annotationType']).value
        values_insert = []
        values_update = []

        meta = (None if not 'meta' in submissions else json.dumps(submissions['meta']))

        # for deletion: remove all annotations whose image ID matches but whose annotation ID is not among the submitted ones
        ids = []

        viewcountValues = []
        for imageKey in submissions['entries']:
            entry = submissions['entries'][imageKey]

            try:
                lastChecked = entry['timeCreated']
                lastTimeRequired = entry['timeRequired']
                if lastTimeRequired is None: lastTimeRequired = 0
            except Exception:
                lastChecked = datetime.now(tz=pytz.utc)
                lastTimeRequired = 0

            try:
                numInteractions = int(entry['numInteractions'])
            except Exception:
                numInteractions = 0

            if 'annotations' in entry and len(entry['annotations']):
                for annotation in entry['annotations']:
                    # assemble annotation values
                    annotationTokens = self.annoParser.parseAnnotation(annotation)
                    annoValues = []
                    for cname in colnames:
                        if cname == 'id':
                            if cname in annotationTokens:
                                # cast and only append id if the annotation is an existing one
                                annoValues.append(UUID(annotationTokens[cname]))
                                ids.append(UUID(annotationTokens[cname]))
                        elif cname == 'image':
                            annoValues.append(UUID(imageKey))
                        elif cname == 'label' and annotationTokens[cname] is not None:
                            annoValues.append(UUID(annotationTokens[cname]))
                        elif cname == 'timeCreated':
                            try:
                                annoValues.append(dateutil.parser.parse(annotationTokens[cname]))
                            except Exception:
                                annoValues.append(datetime.now(tz=pytz.utc))
                        elif cname == 'timeRequired':
                            timeReq = annotationTokens[cname]
                            if timeReq is None: timeReq = 0
                            annoValues.append(timeReq)
                        elif cname == 'username':
                            annoValues.append(username)
                        elif cname in annotationTokens:
                            annoValues.append(annotationTokens[cname])
                        elif cname == 'unsure':
                            if 'unsure' in annotationTokens and annotationTokens['unsure'] is not None:
                                annoValues.append(annotationTokens[cname])
                            else:
                                annoValues.append(False)
                        elif cname == 'meta':
                            annoValues.append(meta)
                        else:
                            annoValues.append(None)
                    if 'id' in annotationTokens:
                        # existing annotation; update
                        values_update.append(tuple(annoValues))
                    else:
                        # new annotation
                        values_insert.append(tuple(annoValues))
                    
            viewcountValues.append((username, imageKey, 1, lastChecked, lastChecked, lastTimeRequired, lastTimeRequired, numInteractions, meta))


        # delete all annotations that are not in submitted batch
        imageKeys = list(UUID(k) for k in submissions['entries'])
        if len(imageKeys):
            if len(ids):
                queryStr = sql.SQL('''
                    DELETE FROM {id_anno} WHERE username = %s AND id IN (
                        SELECT idQuery.id FROM (
                            SELECT * FROM {id_anno} WHERE id NOT IN %s
                        ) AS idQuery
                        JOIN (
                            SELECT * FROM {id_anno} WHERE image IN %s
                        ) AS imageQuery ON idQuery.id = imageQuery.id);
                ''').format(
                    id_anno=sql.Identifier(project, 'annotation'))
                self.dbConnector.execute(queryStr, (username, tuple(ids), tuple(imageKeys),))
            else:
                # no annotations submitted; delete all annotations submitted before
                queryStr = sql.SQL('''
                    DELETE FROM {id_anno} WHERE username = %s AND image IN %s;
                ''').format(
                    id_anno=sql.Identifier(project, 'annotation'))
                self.dbConnector.execute(queryStr, (username, tuple(imageKeys),))

        # insert new annotations
        if len(values_insert):
            queryStr = sql.SQL('''
                INSERT INTO {id_anno} ({cols})
                VALUES %s ;
            ''').format(
                id_anno=sql.Identifier(project, 'annotation'),
                cols=sql.SQL(', ').join([sql.SQL(c) for c in colnames[1:]])     # skip 'id' column
            )
            self.dbConnector.insert(queryStr, values_insert)

        # update existing annotations
        if len(values_update):

            updateCols = []
            for col in colnames:
                if col == 'label':
                    updateCols.append(sql.SQL('label = UUID(e.label)'))
                elif col == 'timeRequired':
                    # we sum the required times together
                    updateCols.append(sql.SQL('timeRequired = COALESCE(a.timeRequired,0) + COALESCE(e.timeRequired,0)'))
                else:
                    updateCols.append(sql.SQL('{col} = e.{col}').format(col=sql.SQL(col)))

            queryStr = sql.SQL('''
                UPDATE {id_anno} AS a
                SET {updateCols}
                FROM (VALUES %s) AS e({colnames})
                WHERE e.id = a.id
            ''').format(
                id_anno=sql.Identifier(project, 'annotation'),
                updateCols=sql.SQL(', ').join(updateCols),
                colnames=sql.SQL(', ').join([sql.SQL(c) for c in colnames])
            )

            self.dbConnector.insert(queryStr, values_update)


        # viewcount table
        queryStr = sql.SQL('''
            INSERT INTO {id_iu} (username, image, viewcount, first_checked, last_checked, last_time_required, total_time_required, num_interactions, meta)
            VALUES %s 
            ON CONFLICT (username, image) DO UPDATE SET viewcount = image_user.viewcount + 1,
                last_checked = EXCLUDED.last_checked,
                last_time_required = EXCLUDED.last_time_required,
                total_time_required = EXCLUDED.total_time_required + image_user.total_time_required,
                num_interactions = EXCLUDED.num_interactions + image_user.num_interactions,
                meta = EXCLUDED.meta;
        ''').format(
            id_iu=sql.Identifier(project, 'image_user')
        )
        self.dbConnector.insert(queryStr, viewcountValues)

        return 0


    def getGoldenQuestions(self, project):
        '''
            Returns a list of image UUIDs and their file names that have been flagged
            as golden questions for a given project.
            TODO: augment tables with who added the golden question and when it
            happened...
        '''
        queryStr = sql.SQL('SELECT id, filename FROM {id_img} WHERE isGoldenQuestion = true;').format(
            id_img=sql.Identifier(project, 'image')
        )
        result = self.dbConnector.execute(queryStr, None, 'all')
        result = [(str(r['id']), r['filename']) for r in result]
        return {
            'status': 0,
            'images': result
        }


    def setGoldenQuestions(self, project, submissions):
        '''
            Receives an iterable of tuples (uuid, bool) and updates the
            property "isGoldenQuestion" of the images accordingly.
        '''
        if common.check_demo_mode(project, self.dbConnector):
            return {
                'status': 2,
                'message': 'Not allowed in demo mode.'
            }

        projImmutables = self.get_project_immutables(project)

        queryStr = sql.SQL('''
            UPDATE {id_img} AS img SET isGoldenQuestion = c.isGoldenQuestion
            FROM (VALUES %s)
            AS c (id, isGoldenQuestion)
            WHERE c.id = img.id
            RETURNING img.id, img.isGoldenQuestion;
        ''').format(
            id_img=sql.Identifier(project, 'image')
        )
        result = self.dbConnector.insert(queryStr, submissions, 'all')
        imgs_result = {}
        for r in result:
            imgs_result[str(r[0])] = r[1]

        return {
            'status': 0,
            'golden_questions': imgs_result
        }


    def getBookmarks(self, project, user):
        '''
            Returns a list of image UUIDs and file names that have been bookmarked by a
            given user, along with the timestamp at which the bookmarks got created.
        '''
        queryStr = sql.SQL('''SELECT image, filename, EXTRACT(epoch FROM timeCreated) AS timeCreated
            FROM {id_bookmark} AS bm
            JOIN {id_img} AS img
            ON bm.image = img.id
            WHERE username = %s
            ORDER BY timeCreated DESC;
        ''').format(
            id_bookmark=sql.Identifier(project, 'bookmark'),
            id_img=sql.Identifier(project, 'image')
        )
        result = self.dbConnector.execute(queryStr, (user,), 'all')
        result = [(str(r['image']), r['filename'], r['timecreated']) for r in result]
        return {
            'status': 0,
            'bookmarks': result
        }


    def setBookmark(self, project, user, bookmarks):
        '''
            Receives a user name and a dict of image IDs (key)
            and whether they should become bookmarks (True) or
            be removed from the list (False).
        '''
        if bookmarks is None or not isinstance(bookmarks, dict) or len(bookmarks.keys()) == 0:
            return {
                'status': 2,
                'message': 'No images provided.'
            }

        # prepare IDs
        imgs_success = []
        imgs_error = []
        imgs_set, imgs_clear = [], []

        for b in bookmarks:
            try:
                imageID = UUID(b)
                if bool(bookmarks[b]):
                    imgs_set.append(tuple((user, imageID)))
                else:
                    imgs_clear.append(imageID)
            except Exception:
                imgs_error.append(b)
        imgs_error = set(imgs_error)

        # insert new bookmarks
        if len(imgs_set):
            queryStr = sql.SQL('''
                INSERT INTO {id_bookmark} (username, image)
                SELECT val.username, val.imgID
                FROM (
                    VALUES %s
                ) AS val (username, imgID)
                JOIN (
                    SELECT id AS imgID FROM {id_img}
                ) AS img USING (imgID)
                ON CONFLICT (username, image) DO NOTHING
                RETURNING image;
            ''').format(
                id_bookmark=sql.Identifier(project, 'bookmark'),
                id_img=sql.Identifier(project, 'image')
            )
            result = self.dbConnector.execute(queryStr, imgs_set, 'all')
            imageIDs_set = set([str(i[1]) for i in imgs_set])
            for r in result:
                imageID = str(r['image'])
                if imageID not in imageIDs_set:
                    imgs_error.add(imageID)
                else:
                    imgs_success.append(imageID)
        
        # remove existing bookmarks
        if len(imgs_clear):
            queryStr = sql.SQL('''
                DELETE FROM {id_bookmark}
                WHERE username = %s
                AND image IN %s
                RETURNING image;
            ''').format(
                id_bookmark=sql.Identifier(project, 'bookmark')
            )
            result = self.dbConnector.execute(queryStr, (user, tuple(imgs_clear)), 'all')
            for r in result:
                imageID = str(r['image'])
                imgs_success.append(imageID)

            imgs_error.update(set(imgs_clear).difference(set([r['image'] for r in result])))

        response = {
            'status': 0,
            'bookmarks_success': imgs_success
        }
        if len(imgs_error):
            imgs_error = [str(i) for i in list(imgs_error)]
            response['bookmarks_error'] = imgs_error
        
        return response