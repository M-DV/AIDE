'''
    Definition of the layer between the UI frontend and the database.

    2019-24 Benjamin Kellenberger
'''

import os
from typing import Iterable, Union
from uuid import UUID
from datetime import datetime
import json
import pytz
import dateutil.parser
from PIL import Image
from psycopg2 import sql

from util import helpers, common
from . import sql_string_builder
from .annotation_sql_tokens import QueryStrings_annotation, AnnotationParser



class DBMiddleware():
    '''
        Label UI middleware, performing communication between frontend and the database.
    '''
    def __init__(self, config, db_connector) -> None:
        self.config = config
        self.db_connector = db_connector

        # project settings that cannot be changed (project shorthand -> {settings})
        self.project_immutables = {}

        self._fetch_project_settings()
        self.anno_parser = AnnotationParser()


    def _fetch_project_settings(self) -> None:
        # AI controller URI
        ai_controller_uri = self.config.get_property('Server', 'aiController_uri')
        if ai_controller_uri is None or ai_controller_uri.strip() == '':
            # no AI backend configured
            ai_controller_uri = None

        # global, project-independent settings
        self.global_settings = {
            'indexURI': self.config.get_property('Server',
                                                 'index_uri',
                                                 dtype=str,
                                                 fallback='/'),
            'dataServerURI': self.config.get_property('Server', 'dataServer_uri'),
            'aiControllerURI': ai_controller_uri,

        }
        max_image_size = (self.config.get_property('LabelUI',
                                                   'max_image_height',
                                                   dtype=int,
                                                   fallback=None),
                          self.config.get_property('LabelUI',
                                                   'max_image_width',
                                                   dtype=int,
                                                   fallback=None))
        if all(val is None for val in max_image_size):
            self.max_image_size = None
        self.global_settings['maxImageSize'] = max_image_size

        # default styles
        try:
            # check if custom default styles are provided
            with open('config/default_ui_settings.json', 'r', encoding='utf-8') as f_styles:
                self.default_styles = json.load(f_styles)
        except Exception:
            # resort to built-in styles
            with open('modules/ProjectAdministration/static/json/default_ui_settings.json',
                      'r',
                      encoding='utf-8') as f_default:
                self.default_styles = json.load(f_default)


    def _assemble_annotations(self,
                              project: str,
                              query_data: list,
                              hide_golden_question_info: bool) -> dict:
        response = {}
        for row in query_data:
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

            if not hide_golden_question_info:
                response[img_id]['isGoldenQuestion'] = row['isgoldenquestion']

            response[img_id]['isBookmarked'] = row['isbookmarked']

            # parse annotations and predictions
            entry_id = str(row['id'])
            if row['ctype'] is not None:
                colnames = sql_string_builder.get_colnames(
                    self.project_immutables[project]['annotationType'],
                    self.project_immutables[project]['predictionType'],
                    row['ctype'])
                entry = {}
                for colname in colnames:
                    value = row[colname]
                    if isinstance(value, datetime):
                        value = value.timestamp()
                    elif isinstance(value, UUID):
                        value = str(value)
                    entry[colname] = value

                if row['ctype'] == 'annotation':
                    response[img_id]['annotations'][entry_id] = entry
                elif row['ctype'] == 'prediction':
                    response[img_id]['predictions'][entry_id] = entry

        return response


    def _set_images_requested(self,
                              project: str,
                              image_ids: Iterable[UUID]) -> None:
        '''
            Sets column "last_requested" of relation "image" to the current date. This is done
            during image querying to signal that an image has been requested, but not (yet) viewed.
        '''
        # prepare insertion values
        now = datetime.now(tz=pytz.utc)
        vals = []
        for key in image_ids:
            vals.append(key)
        if len(vals) > 0:
            query_str = sql.SQL('''
                UPDATE {id_img}
                SET last_requested = %s
                WHERE id IN %s;
            ''').format(id_img=sql.Identifier(project, 'image'))
            self.db_connector.execute(query_str, (now, tuple(vals),), None)


    def _get_sample_metadata(self, meta_type: str) -> dict:
        '''
            Returns a dummy annotation or prediction for the sample image in the "exampleData"
            folder, depending on the "metaType" specified (i.e., labels, points, boundingBoxes, or
            segmentationMasks).
        '''
        if meta_type == 'labels':
            return {
                'id': '00000000-0000-0000-0000-000000000000',
                'label': '00000000-0000-0000-0000-000000000000',
                'confidence': 1.0,
                'priority': 1.0,
                'viewcount': None
            }
        if meta_type in ('points', 'boundingBoxes'):
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
        if meta_type == 'polygons':
            with open('modules/LabelUI/static/exampleData/sample_polygon.json',
                      'r',
                      encoding='utf-8') as f_polygon:
                return json.load(f_polygon)
        if meta_type == 'segmentationMasks':
            # read segmentation mask from disk
            segmask = Image.open('modules/LabelUI/static/exampleData/sample_segmentationMask.tif')
            segmask, width, height = helpers.image_to_base64(segmask)
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


    def get_project_immutables(self, project: str) -> dict:
        '''
            Returns project properties that are immutable (currently: the project's annotation and
            prediction types). Caches values
            for reduced database access in future.

            Args:
                - "project": str, project shortname

            Returns:
                dict, the project's immutable properties
        '''
        if self.project_immutables.get(project, {}) is None:
            return None
        if project not in self.project_immutables:
            anno_type, pred_type = common.get_project_immutables(project, self.db_connector)
            if anno_type is None or pred_type is None:
                self.project_immutables[project] = None
                return None
            self.project_immutables[project] = {
                'annotationType': anno_type,
                'predictionType': pred_type
            }
        return self.project_immutables[project]


    def get_project_ui_settings(self, project: str) -> dict:
        '''
            Returns the project's user interface settings).

            Args:
                - "project": str, project shortname

            Returns:
                dict, the project's UI settings
        '''
        query_str = 'SELECT ui_settings FROM aide_admin.project WHERE shortname = %s;'
        result = self.db_connector.execute(query_str, (project,), 1)
        result = json.loads(result[0]['ui_settings'])

        # complete styles with defaults where necessary
        # (may be required for project that got upgraded from v1)
        result = helpers.check_args(result, self.default_styles)

        return result


    def get_project_settings(self, project: str) -> dict:
        '''
            Queries the database for general project-specific metadata, such as:
            - Classes: names, indices, default colors
            - Annotation type: one of {class labels, positions, bboxes}
        '''
        # publicly available info from DB
        proj_settings = self.get_project_info(project)

        # label classes
        proj_settings['classes'] = self.get_class_definitions(project)

        # static and dynamic project settings and properties from configuration file
        proj_settings = {**proj_settings,
                         **self.get_project_immutables(project),
                         **self.get_project_ui_settings(project),
                         **self.global_settings}

        # append project shorthand to AIController URI
        if 'aiControllerURI' in proj_settings and \
            proj_settings['aiControllerURI'] is not None and \
                len(proj_settings['aiControllerURI']) > 0:
            proj_settings['aiControllerURI'] = os.path.join(proj_settings['aiControllerURI'],
                                                            project) + '/'

        return proj_settings


    def get_project_info(self, project: str) -> dict:
        '''
            Returns safe, shareable information about the project
            (i.e., users don't need to be part of the project to see these data).

            #TODO: partially redundant with ProjectAdministration middleware function
        '''
        query_str = '''
            SELECT shortname, name, description, demoMode,
            interface_enabled, archived, ai_model_enabled,
            ai_model_library, ai_alcriterion_library,
            segmentation_ignore_unlabeled
            FROM aide_admin.project
            WHERE shortname = %s
        '''
        result = self.db_connector.execute(query_str, (project,), 1)[0]

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


    def get_class_definitions(self,
                              project: str,
                              show_hidden: bool=False) -> dict:
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
                sql.SQL('' if show_hidden else 'WHERE hidden IS false')
            )

        class_data = self.db_connector.execute(query_str, None, 'all')

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


    def get_batch_fixed(self,
                        project: str,
                        username: str,
                        image_ids: Iterable[Union[UUID,str]],
                        hide_golden_question_info=True) -> dict:
        '''
            Returns entries from the database based on the list of data entry identifiers specified.
        '''

        if len(image_ids) == 0:
            return { 'entries': {} }

        # query
        proj_immutables = self.get_project_immutables(project)
        is_demo_mode = common.check_demo_mode(project, self.db_connector)
        query_str = sql_string_builder.get_fixed_images_query_str(project,
                                                                  proj_immutables['annotationType'],
                                                                  proj_immutables['predictionType'],
                                                                  is_demo_mode)

        # verify provided UUIDs
        uuids = []
        imgs_malformed = []
        for img_id in image_ids:
            if not isinstance(img_id, UUID):
                try:
                    uuids.append(UUID(img_id))
                except Exception:
                    imgs_malformed.append(img_id)
            else:
                uuids.append(img_id)
        uuids = tuple(uuids)

        if len(uuids) == 0:
            return {
                'entries': {},
                'imgs_malformed': imgs_malformed
            }

        # parse results
        if is_demo_mode:
            query_vals = (uuids,)
        else:
            query_vals = (uuids, username, username,)

        anno_result = self.db_connector.execute(query_str,
                                                query_vals,
                                                'all')
        try:
            response = self._assemble_annotations(project,
                                                  anno_result,
                                                  hide_golden_question_info)
        except Exception as exc:
            print(exc)      #TODO

        # filter out images that are invalid
        imgs_malformed = list(set(imgs_malformed).union(
                                set(image_ids).difference(set(response.keys()))))

        # mark images as requested
        self._set_images_requested(project, response)

        response = {
            'entries': response
        }
        if len(imgs_malformed) > 0:
            response['imgs_malformed'] = imgs_malformed

        return response


    def get_batch_auto(self,
                       project: str,
                       username: str,
                       order: str='unlabeled',
                       subset: str='default',
                       limit: int=None,
                       hide_golden_question_info: bool=True) -> dict:
        '''
            TODO: description
        '''
        # query
        proj_immutables = self.get_project_immutables(project)
        is_demo_mode = common.check_demo_mode(project, self.db_connector)
        query_str = sql_string_builder.get_next_batch_query_str(project,
                                                                proj_immutables['annotationType'],
                                                                proj_immutables['predictionType'],
                                                                order,
                                                                subset,
                                                                is_demo_mode)

        # limit (TODO: make 128 a hyperparameter)
        if limit is None:
            limit = 128
        else:
            limit = min(int(limit), 128)

        # parse results
        query_vals = (username,username,limit,username,)
        if is_demo_mode:
            query_vals = (limit,)

        anno_result = self.db_connector.execute(query_str,
                                                query_vals,
                                                'all')
        try:
            response = self._assemble_annotations(project,
                                                  anno_result,
                                                  hide_golden_question_info)

            # mark images as requested (TODO: place into finally clause?)
            self._set_images_requested(project, response)
        except Exception as e:
            print(e)
            return { 'entries': {}}

        return { 'entries': response }


    def get_batch_time_range(self,
                             project: str,
                             min_timestamp: float,
                             max_timestamp: float,
                             user_list: Iterable[str],
                             skip_empty_images: bool=False,
                             limit: int=None,
                             golden_questions_only: bool=False,
                             hide_golden_question_info: bool=True,
                             last_image_uuid: Union[UUID,str]=None) -> dict:
        '''
            Returns images that have been annotated within the given time range and/or by the given
            user(s). All arguments are optional. Useful for reviewing existing annotations.
        '''
        # query string
        proj_immutables = self.get_project_immutables(project)
        if isinstance(last_image_uuid, str):
            last_image_uuid = UUID(last_image_uuid)
        query_str = sql_string_builder.get_date_query_str(project,
                                                          proj_immutables['annotationType'],
                                                          min_timestamp,
                                                          max_timestamp,
                                                          user_list,
                                                          skip_empty_images,
                                                          golden_questions_only,
                                                          last_image_uuid)

        # check validity and provide arguments
        query_vals = []
        if user_list is not None:
            query_vals.append(tuple(user_list))
        if min_timestamp is not None:
            query_vals.append(min_timestamp)
        if max_timestamp is not None:
            query_vals.append(max_timestamp)
        if last_image_uuid is not None:
            query_vals.append(last_image_uuid)
        if skip_empty_images and user_list is not None:
            query_vals.append(tuple(user_list))

        # limit (TODO: make 128 a hyperparameter)
        if limit is None:
            limit = 128
        else:
            limit = min(int(limit), 128)
        query_vals.append(limit)

        if user_list is not None:
            query_vals.append(tuple(user_list))

        # query and parse results
        anno_result = self.db_connector.execute(query_str,
                                                tuple(query_vals),
                                                'all')
        try:
            response = self._assemble_annotations(project,
                                                  anno_result,
                                                  hide_golden_question_info)
        except Exception as exc:
            print(exc)      #TODO

        # # mark images as requested
        # self._set_images_requested(project, response)

        return { 'entries': response }


    def get_time_range(self,
                       project: str,
                       user_list: Iterable[str],
                       skip_empty_images: bool=False,
                       golden_questions_only: bool=False) -> dict:
        '''
            Returns two timestamps denoting the temporal limits within which images have been viewed
            by the users provided in the userList.
            
            Args:
                - user_list:                str (single user name) or list of strings (multiple).
                                            Can also be None; in this case all annotations will be
                                            checked.
                - skip_empty_images:        bool, if True, only images that contain at least one
                                            annotation will be considered (default: False).
                - golden_questions_only:    bool, if True, only images flagged as golden questions
                                            will be shown (default: False).
            
            Returns:
                - dict, containing "minTimestamp" and "maxTimestamp" (floats) or else an error
                  message if no annotations could be found.
        '''
        # query string
        query_str = sql_string_builder.get_time_range_query_str(project,
                                                                user_list,
                                                                skip_empty_images,
                                                                golden_questions_only)

        arguments = (None if user_list is None else tuple(user_list))
        result = self.db_connector.execute(query_str,
                                           (arguments,),
                                           numReturn=1)

        if result is not None and len(result):
            return {
                'minTimestamp': result[0]['mintimestamp'],
                'maxTimestamp': result[0]['maxtimestamp'],
            }
        return {
            'error': 'no annotations made'
        }


    def get_image_cardinal_direction(self,
                                     project: str,
                                     username: str,
                                     current_image_id: Union[str, UUID],
                                     cardinal_direction: str,
                                     hide_golden_question_info: bool=True) -> dict:
        '''
            Returns the next image in given cardinal direction, based on the current one. Only works
            if the following criteria are met:
                1. The current image is a tile of a bigger one (i.e., it has x, y, width, height
                   defined in the database entry)
                2. There actually is another tile in given cardinal direction

            If any of the criteria is not fulfilled, an empty dict is returned.

            Also returns image UUIDs in all four cardinal directions in general.
        '''
        if isinstance(current_image_id, str):
            current_image_id = UUID(current_image_id)

        # get UUID of next tile in direction
        query_str = sql_string_builder.get_next_tile_cardinal_direction_query_str(project)
        next_uuids = self.db_connector.execute(query_str,
                                               (current_image_id,),
                                               4)
        next_uuids = dict([row['cd'], str(row['id'])] for row in next_uuids)
        cardinal_direction = cardinal_direction.strip().lower()
        if cardinal_direction not in next_uuids:
            entries = {}
        else:
            # re-query available cardinal directions for next image
            next_uuid = next_uuids[cardinal_direction]
            next_uuids = self.db_connector.execute(query_str,
                                                   (next_uuid,),
                                                   4)
            next_uuids = dict([row['cd'], str(row['id'])] for row in next_uuids)

            entries = self.get_batch_fixed(project,
                                           username,
                                           (next_uuid,),
                                           hide_golden_question_info)
        entries['cd'] = next_uuids
        return entries


    def get_sample_data(self, project: str) -> dict:
        '''
            Returns a sample image from the project, with annotations (from one of the admins) and
            predictions. If no image, no annotations, and/or no predictions are available, a
            built-in default is returned instead.
        '''
        proj_immutables = self.get_project_immutables(project)
        query_str = sql_string_builder.get_sample_data_query_str(project,
                                                                 proj_immutables['annotationType'],
                                                                 proj_immutables['predictionType'])

        # query and parse results
        response = None
        anno_result = self.db_connector.execute(query_str, None, 'all')
        try:
            response = self._assemble_annotations(project, anno_result, True)
        except Exception as exc:
            print(exc)      #TODO

        if response is None or len(response) == 0:
            # no valid data found for project; fall back to sample data
            response = {
                '00000000-0000-0000-0000-000000000000': {
                    'fileName': '/static/interface/exampleData/sample_image.jpg',
                    'viewcount': 1,
                    'annotations': {
                        '00000000-0000-0000-0000-000000000000': \
                            self._get_sample_metadata(proj_immutables['annotationType'])
                    },
                    'predictions': {
                        '00000000-0000-0000-0000-000000000000': \
                            self._get_sample_metadata(proj_immutables['predictionType'])
                    },
                    'last_checked': None,
                    'isGoldenQuestion': True
                }
            }
        return response


    def submit_annotations(self,
                           project: str,
                           username: str,
                           submissions: dict) -> int:
        '''
            Sends user-provided annotations to the database.
        '''
        if common.check_demo_mode(project, self.db_connector):
            return 1

        proj_immutables = self.get_project_immutables(project)

        # assemble values
        colnames = getattr(QueryStrings_annotation, proj_immutables['annotationType']).value
        values_insert = []
        values_update = []

        meta = (None if not 'meta' in submissions else json.dumps(submissions['meta']))

        # for deletion: remove all annotations whose image ID matches but whose annotation ID is not
        # among the submitted ones
        ids = []

        viewcount_vals = []
        for image_key, entry in submissions['entries'].items():

            try:
                last_checked = entry['timeCreated']
                last_time_required = entry.get('timeRequired', 0)
                if last_time_required is None:
                    last_time_required = 0
            except Exception:
                last_checked = datetime.now(tz=pytz.utc)
                last_time_required = 0

            num_interactions = int(entry.get('numInteractions', 0))

            if 'annotations' in entry and len(entry['annotations']) > 0:
                for annotation in entry['annotations']:
                    # assemble annotation values
                    anno_tokens = self.anno_parser.parseAnnotation(annotation)
                    anno_vals = []
                    for cname in colnames:
                        if cname == 'id':
                            if cname in anno_tokens:
                                # cast and only append id if the annotation is an existing one
                                anno_vals.append(UUID(anno_tokens[cname]))
                                ids.append(UUID(anno_tokens[cname]))
                        elif cname == 'image':
                            anno_vals.append(UUID(image_key))
                        elif cname == 'label' and anno_tokens[cname] is not None:
                            anno_vals.append(UUID(anno_tokens[cname]))
                        elif cname == 'timeCreated':
                            try:
                                anno_vals.append(dateutil.parser.parse(anno_tokens[cname]))
                            except Exception:
                                anno_vals.append(datetime.now(tz=pytz.utc))
                        elif cname == 'timeRequired':
                            time_required = anno_tokens[cname]
                            if time_required is None:
                                time_required = 0
                            anno_vals.append(time_required)
                        elif cname == 'username':
                            anno_vals.append(username)
                        elif cname in anno_tokens:
                            anno_vals.append(anno_tokens[cname])
                        elif cname == 'unsure':
                            if 'unsure' in anno_tokens and anno_tokens['unsure'] is not None:
                                anno_vals.append(anno_tokens[cname])
                            else:
                                anno_vals.append(False)
                        elif cname == 'meta':
                            anno_vals.append(meta)
                        else:
                            anno_vals.append(None)
                    if 'id' in anno_tokens:
                        # existing annotation; update
                        values_update.append(tuple(anno_vals))
                    else:
                        # new annotation
                        values_insert.append(tuple(anno_vals))

            viewcount_vals.append((username,
                                   image_key,
                                   1,
                                   last_checked,
                                   last_checked,
                                   last_time_required,
                                   last_time_required,
                                   num_interactions,
                                   meta))


        # delete all annotations that are not in submitted batch
        image_keys = list(UUID(key) for key in submissions['entries'])
        if len(image_keys) > 0:
            if len(ids) > 0:
                query_str = sql.SQL('''
                    DELETE FROM {id_anno} WHERE username = %s AND id IN (
                        SELECT idQuery.id FROM (
                            SELECT * FROM {id_anno} WHERE id NOT IN %s
                        ) AS idQuery
                        JOIN (
                            SELECT * FROM {id_anno} WHERE image IN %s
                        ) AS imageQuery ON idQuery.id = imageQuery.id);
                ''').format(
                    id_anno=sql.Identifier(project, 'annotation'))
                self.db_connector.execute(query_str, (username, tuple(ids), tuple(image_keys),))
            else:
                # no annotations submitted; delete all annotations submitted before
                query_str = sql.SQL('''
                    DELETE FROM {id_anno} WHERE username = %s AND image IN %s;
                ''').format(
                    id_anno=sql.Identifier(project, 'annotation'))
                self.db_connector.execute(query_str, (username, tuple(image_keys),))

        # insert new annotations
        if len(values_insert) > 0:
            query_str = sql.SQL('''
                INSERT INTO {id_anno} ({cols})
                VALUES %s ;
            ''').format(
                id_anno=sql.Identifier(project, 'annotation'),
                cols=sql.SQL(', ').join([sql.SQL(col) for col in colnames[1:]])     # skip id col
            )
            self.db_connector.insert(query_str, values_insert)

        # update existing annotations
        if len(values_update) > 0:
            cols_update = []
            for col in colnames:
                if col == 'label':
                    cols_update.append(sql.SQL('label = UUID(e.label)'))
                elif col == 'timeRequired':
                    # we sum the required times together
                    cols_update.append(sql.SQL('timeRequired = COALESCE(a.timeRequired,0) + ' + \
                                               'COALESCE(e.timeRequired,0)'))
                else:
                    cols_update.append(sql.SQL('{col} = e.{col}').format(col=sql.SQL(col)))

            query_str = sql.SQL('''
                UPDATE {id_anno} AS a
                SET {updateCols}
                FROM (VALUES %s) AS e({colnames})
                WHERE e.id = a.id
            ''').format(
                id_anno=sql.Identifier(project, 'annotation'),
                updateCols=sql.SQL(', ').join(cols_update),
                colnames=sql.SQL(', ').join([sql.SQL(col) for col in colnames])
            )

            self.db_connector.insert(query_str, values_update)

        # viewcount table
        query_str = sql.SQL('''
            INSERT INTO {id_iu} (username, image, viewcount, first_checked, last_checked,
                last_time_required, total_time_required, num_interactions, meta)
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
        self.db_connector.insert(query_str, viewcount_vals)

        return 0


    def get_golden_questions(self, project: str) -> dict:
        '''
            Returns a list of image UUIDs and their file names that have been flagged as golden
            questions for a given project. TODO: augment tables with who added the golden question
            and when it happened...
        '''
        query_str = sql.SQL('SELECT id, filename FROM {id_img} ' + \
                            'WHERE isGoldenQuestion = true;').format(
                id_img=sql.Identifier(project, 'image')
            )
        result = self.db_connector.execute(query_str, None, 'all')
        result = [(str(res['id']), res['filename']) for res in result]
        return {
            'status': 0,
            'images': result
        }


    def set_golden_questions(self,
                             project: str,
                             submissions: tuple) -> dict:
        '''
            Receives an iterable of tuples (uuid, bool) and updates the property "isGoldenQuestion"
            of the images accordingly.
        '''
        if common.check_demo_mode(project, self.db_connector):
            return {
                'status': 2,
                'message': 'Not allowed in demo mode.'
            }

        query_str = sql.SQL('''
                UPDATE {id_img} AS img SET isGoldenQuestion = c.isGoldenQuestion
                FROM (VALUES %s)
                AS c (id, isGoldenQuestion)
                WHERE c.id = img.id
                RETURNING img.id, img.isGoldenQuestion;
            ''').format(
                id_img=sql.Identifier(project, 'image')
            )
        result = self.db_connector.insert(query_str,
                                          submissions,
                                          'all')
        imgs_result = {}
        for res in result:
            imgs_result[str(res[0])] = res[1]

        return {
            'status': 0,
            'golden_questions': imgs_result
        }


    def get_bookmarks(self,
                      project: str,
                      user: str) -> dict:
        '''
            Returns a list of image UUIDs and file names that have been bookmarked by a given user,
            along with the timestamp at which the bookmarks got created.
        '''
        query_str = sql.SQL('''SELECT image, filename,
                EXTRACT(epoch FROM timeCreated) AS timeCreated
                FROM {id_bookmark} AS bm
                JOIN {id_img} AS img
                ON bm.image = img.id
                WHERE username = %s
                ORDER BY timeCreated DESC;
            ''').format(
                id_bookmark=sql.Identifier(project, 'bookmark'),
                id_img=sql.Identifier(project, 'image')
            )
        result = self.db_connector.execute(query_str,
                                           (user,),
                                           'all')
        result = [(str(res['image']), res['filename'], res['timecreated']) for res in result]
        return {
            'status': 0,
            'bookmarks': result
        }


    def set_bookmarks(self,
                      project: str,
                      user: str,
                      bookmarks: dict) -> dict:
        '''
            Receives a user name and a dict of image IDs (key) and whether they should become
            bookmarks (True) or be removed from the list (False).
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

        for bookmark in bookmarks:
            try:
                image_id = UUID(bookmark)
                if bool(bookmarks[bookmark]):
                    imgs_set.append(tuple((user, image_id)))
                else:
                    imgs_clear.append(image_id)
            except Exception:
                imgs_error.append(bookmark)
        imgs_error = set(imgs_error)

        # insert new bookmarks
        if len(imgs_set) > 0:
            query_str = sql.SQL('''
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
            result = self.db_connector.execute(query_str,
                                               imgs_set,
                                               'all')
            image_ids_set = set(str(img[1]) for img in imgs_set)
            for res in result:
                image_id = str(res['image'])
                if image_id not in image_ids_set:
                    imgs_error.add(image_id)
                else:
                    imgs_success.append(image_id)

        # remove existing bookmarks
        if len(imgs_clear) > 0:
            query_str = sql.SQL('''
                DELETE FROM {id_bookmark}
                WHERE username = %s
                AND image IN %s
                RETURNING image;
            ''').format(
                id_bookmark=sql.Identifier(project, 'bookmark')
            )
            result = self.db_connector.execute(query_str,
                                               (user, tuple(imgs_clear)),
                                               'all')
            for res in result:
                image_id = str(res['image'])
                imgs_success.append(image_id)

            imgs_error.update(set(imgs_clear).difference(set(res['image'] for res in result)))

        response = {
            'status': 0,
            'bookmarks_success': imgs_success
        }
        if len(imgs_error) > 0:
            imgs_error = [str(img) for img in list(imgs_error)]
            response['bookmarks_error'] = imgs_error

        return response


    def get_tags(self, project: str) -> dict:
        '''
            Returns all the tags created for a given project.
        '''
        tags = self.db_connector.execute(sql.SQL('''
                SELECT * FROM {id_tag} AS f
                LEFT OUTER JOIN (
                    SELECT tag_id, COUNT(*) AS num_img
                    FROM {id_tagImage}
                    GROUP BY tag_id
                ) AS f_count
                ON f.id = f_count.tag_id;
            ''').format(id_tag=sql.Identifier(project, 'tag'),
                        id_tagImage=sql.Identifier(project, 'tag_image')),
            None,
            'all')
        tags = [{'id': str(row['id']),
                 'name': row['name'],
                 'color': row['color'],
                 'num_img': row['num_img']}
                for row in tags] if tags is not None else []
        return {
            'status': 0,
            'tags': tags
        }


    def save_tags(self,
                  project: str,
                  tags: Iterable[dict]) -> dict:
        '''
            Receives an Iterable of tag properties and saves them for a given project. Removes
            tags (and associated images) not present in the list.
        '''
        result = {}

        # get all existing tag IDs
        tags_project = dict([tag['id'], tag] for tag in self.get_tags(project)['tags'])

        # split into new, to edit, and to delete tags
        tags_new, tags_edit = [], []
        for tag_meta in tags:
            fid = tag_meta.get('id', None)
            fname = tag_meta.get('name', '').strip()
            assert len(fname) > 0, f'Error: empty name for tag with id "{fid}".'
            if fid is not None and fid in tags_project:
                if tags_project[fid]['name'] != tag_meta['name'] or \
                    tags_project[fid]['color'] != tag_meta['color']:
                    tags_edit.append(tag_meta)
            else:
                tags_new.append((fname, tag_meta.get('color', None)))

        # apply the changes
        if len(tags_new) > 0:
            result_new = self.db_connector.insert(sql.SQL('''
                INSERT INTO {id_tag} (name, color)
                VALUES %s
                RETURNING id, name;
                ''').format(id_tag=sql.Identifier(project, 'tag')),
                tags_new,
                'all')
            result['tags_new'] = dict([str(row['id']), row['name']] for row in result_new)

        if len(tags_edit) > 0:
            # apply changes separately for name and color
            edit_vals = [(UUID(entry['id']), entry['name'], entry['color'])
                         for entry in tags_edit]

            query_str = sql.SQL('''
                UPDATE {id_tag} AS f
                SET name=e.name, color=e.color
                FROM (VALUES %s) AS e(id, name, color)
                WHERE e.id = f.id
                RETURNING e.id, e.name
            ''').format(id_tag=sql.Identifier(project, 'tag'))
            result_edit = self.db_connector.insert(query_str,
                                                   edit_vals,
                                                   'all')

            result['tags_edited'] = dict([str(row[0]), row[1]] for row in result_edit)

        # delete tags not present in the list
        tags_delete = frozenset(tags_project.keys()).difference(
                            frozenset(tag['id'] for tag in tags))
        if len(tags_delete) > 0:
            tags_delete = [(UUID(tag),) for tag in tags_delete]
            self.db_connector.insert(sql.SQL('''
                DELETE FROM {id_tagImage}
                WHERE tag_id IN %s;
                ''').format(id_tagImage=sql.Identifier(project, 'tag_image')),
                tags_delete)
            result_delete = self.db_connector.insert(sql.SQL('''
                DELETE FROM {id_tag}
                WHERE id IN %s
                RETURNING id, name;
                ''').format(id_tag=sql.Identifier(project, 'tag')),
                tags_delete,
                'all')
            result['tags_deleted'] = dict([str(row[0]), row[1]] for row in result_delete)
        return result


    def set_tags(self,
                 project: str,
                 tags: Iterable[Union[str,UUID]],
                 image_ids: Iterable[Union[str,UUID]],
                 clear_existing: bool=False) -> dict:
        '''
            Receives an Iterable of tag IDs and an Iterable of image IDs and sets tags for given
            images accordingly. If "tags" is empty or None, tag associations will be removed for
            given images. If "clear_existing" is True, any previously created image-to-tag
            associations will be cleared first.
        '''
        image_ids = [(UUID(iid) if isinstance(iid, str) else iid,) for iid in image_ids]

        if clear_existing or tags is None or len(tags) == 0:
            self.db_connector.insert(sql.SQL('''
                DELETE FROM {id_tag_image}
                WHERE image_id IN (%s);
            ''').format(id_tag_image=sql.Identifier(project, 'tag_image')),
            image_ids)

        if tags is not None and len(tags) > 0:
            tags = [UUID(tid) if isinstance(tid, str) else tid for tid in tags]
            data = [(tag, image_id,) for image_id in image_ids for tag in tags]
            self.db_connector.insert(sql.SQL('''
                INSERT INTO {id_tag_image} (tag_id, image_id)
                VALUES %s
                ON CONFLICT(tag_id, image_id) DO NOTHING;
            ''').format(id_tag_image=sql.Identifier(project, 'tag_image')),
            data)
        return {'status': 0}
