'''
    Definition of AIController tasks that are distributed via Celery (e.g. assembling and splitting
    the lists of training and testing images).

    2020-24 Benjamin Kellenberger
'''

from typing import Union, List
from collections.abc import Iterable
import json
from uuid import UUID
from datetime import datetime
from psycopg2 import sql
from modules.Database.app import Database
from util.helpers import array_split
from .sql_string_builder import SQLStringBuilder



class AIControllerWorker:
    '''
        Class providing functional implementations for AIController module.
    '''
    def __init__(self, config, celery_app):
        self.config = config
        self.db_connector = Database(config)
        self.sql_builder = SQLStringBuilder(config)
        self.celery_app = celery_app


    def _get_num_available_workers(self):
        #TODO: filter for right tasks and queues
        #TODO: limit to n tasks per worker
        i = self.celery_app.control.inspect()
        if i is not None:
            stats = i.stats()
            if stats is not None:
                return len(i.stats())
        return 1    #TODO



    def get_training_images(self,
                            project: str,
                            epoch: int=None,
                            numEpochs: int=None,
                            minTimestamp: Union[datetime,str]='lastState',
                            includeGoldenQuestions: bool=True,
                            minNumAnnoPerImage: int=0,
                            maxNumImages: int=None,
                            numChunks: int=1) -> List[UUID]:
        '''
            Queries the database for the latest images to be used for model training.
            Returns a list with image UUIDs accordingly, split into the number of
            available workers.
        '''
        # sanity checks
        if not (isinstance(minTimestamp, datetime) or minTimestamp == 'lastState' or
                minTimestamp == -1 or minTimestamp is None):
            raise ValueError(f'{minTimestamp} is not a recognized property ' + \
                             'for variable "minTimestamp"')

        # query image IDs
        query_vals = []

        if minTimestamp is None:
            timestamp_str = sql.SQL('')
        elif minTimestamp == 'lastState':
            timestamp_str = sql.SQL('''
            WHERE iu.last_checked > COALESCE(to_timestamp(0),
            (SELECT MAX(timecreated) FROM {id_cnnstate}))''').format(
                id_cnnstate=sql.Identifier(project, 'cnnstate')
            )
        elif isinstance(minTimestamp, datetime):
            timestamp_str = sql.SQL('WHERE iu.last_checked > COALESCE(to_timestamp(0), %s)')
            query_vals.append(minTimestamp)
        elif isinstance(minTimestamp, (int, float)):
            timestamp_str = sql.SQL('''WHERE iu.last_checked > COALESCE(to_timestamp(0),
                                      to_timestamp(%s))''')
            query_vals.append(minTimestamp)

        if minNumAnnoPerImage > 0:
            query_vals.append(minNumAnnoPerImage)

        if maxNumImages is None or maxNumImages <= 0:
            limit_str = sql.SQL('')
        else:
            limit_str = sql.SQL('LIMIT %s')
            query_vals.append(maxNumImages)

        # golden questions
        if includeGoldenQuestions:
            gq_str = sql.SQL('')
        else:
            gq_str = sql.SQL('AND isGoldenQuestion IS NOT TRUE')

        if minNumAnnoPerImage <= 0:
            query_str = sql.SQL('''
                SELECT newestAnno.image FROM (
                    SELECT image, last_checked FROM {id_iu} AS iu
                    JOIN (
                        SELECT id AS iid
                        FROM {id_img}
                        WHERE corrupt IS NULL OR corrupt = FALSE {gqStr}
                    ) AS imgQ
                    ON iu.image = imgQ.iid
                    {timestampStr}
                    ORDER BY iu.last_checked ASC
                    {limitStr}
                ) AS newestAnno;
            ''').format(
                id_iu=sql.Identifier(project, 'image_user'),
                id_img=sql.Identifier(project, 'image'),
                gqStr=gq_str,
                timestampStr=timestamp_str,
                limitStr=limit_str)

        else:
            query_str = sql.SQL('''
                SELECT newestAnno.image FROM (
                    SELECT image, last_checked FROM {id_iu} AS iu
                    JOIN (
                        SELECT id AS iid
                        FROM {id_img}
                        WHERE corrupt IS NULL OR corrupt = FALSE {gqStr}
                    ) AS imgQ
                    ON iu.image = imgQ.iid
                    {timestampStr}
                    {conjunction} image IN (
                        SELECT image FROM (
                            SELECT image, COUNT(*) AS cnt
                            FROM {id_anno}
                            GROUP BY image
                            ) AS annoCount
                        WHERE annoCount.cnt >= %s
                    )
                    ORDER BY iu.last_checked ASC
                    {limitStr}
                ) AS newestAnno;
            ''').format(
                id_iu=sql.Identifier(project, 'image_user'),
                id_img=sql.Identifier(project, 'image'),
                id_anno=sql.Identifier(project, 'annotation'),
                gqStr=gq_str,
                timestampStr=timestamp_str,
                conjunction=(sql.SQL('WHERE') if minTimestamp is None else sql.SQL('AND')),
                limitStr=limit_str)

        image_ids = self.db_connector.execute(query_str, tuple(query_vals), 'all')
        image_ids = [i['image'] for i in image_ids]

        if numChunks > 1:
            # split for distribution across workers (TODO: also specify subset size for multiple
            # jobs; randomly draw if needed)
            image_ids = array_split(image_ids, max(1, len(image_ids) // numChunks))
        else:
            image_ids = [image_ids]

        print(f'Assembled training images into {len(image_ids)} chunks ' + \
              f'(length of first: {len(image_ids[0])})')
        return image_ids



    def get_inference_images(self,
                             project: str,
                             epoch: int=None,
                             numEpochs: int=None,
                             goldenQuestionsOnly: bool=False,
                             forceUnlabeled: bool=False,
                             maxNumImages: int=None,
                             numChunks: int=1) -> List[UUID]:
            '''
                Queries the database for the latest images to be used for inference after model training.
                Returns a list with image UUIDs accordingly, split into the number of available workers.
            '''
            if maxNumImages is None or maxNumImages <= 0:
                query_result = self.db_connector.execute('''
                    SELECT maxNumImages_inference
                    FROM aide_admin.project
                    WHERE shortname = %s;''', (project,), 1)
                maxNumImages = query_result[0]['maxnumimages_inference']
            
            query_vals = (maxNumImages,)

            # load the IDs of the images that are being subjected to inference
            sql_str = self.sql_builder.get_inference_query_string(project,
                                                               forceUnlabeled,
                                                               goldenQuestionsOnly,
                                                               maxNumImages)
            image_ids = self.db_connector.execute(sql_str, query_vals, 'all')
            image_ids = [i['image'] for i in image_ids]
            
            if numChunks > 1:
                image_ids = array_split(image_ids, max(1, len(image_ids) // numChunks))
            else:
                image_ids = [image_ids]
            return image_ids


    
    def delete_model_states(self,
                            project: str,
                            modelStateIDs: Iterable[Union[UUID, str]]) -> List[UUID]:
        '''
            Deletes model states with provided IDs from the database
            for a given project.
        '''
        # verify IDs
        if not isinstance(modelStateIDs, Iterable):
            modelStateIDs = [modelStateIDs]
        model_ids_invalid = []
        query_str_a = sql.SQL('''
                DELETE FROM {id_pred}
                WHERE cnnstate = %s;
            ''').format(
                id_pred=sql.Identifier(project, 'prediction')            )
        query_str_b = sql.SQL('''
                DELETE FROM {id_cnnstate}
                WHERE id = %s;
            ''').format(
                id_cnnstate=sql.Identifier(project, 'cnnstate')
            )
        for idx, model_state_id in enumerate(modelStateIDs):
            print(f'[{project}] Deleting model state {idx+1}/{len(modelStateIDs)}...')
            try:
                if isinstance(model_state_id, UUID):
                    next_id = model_state_id
                else:
                    next_id = UUID(model_state_id)
                self.db_connector.execute(query_str_a, (next_id,))
                self.db_connector.execute(query_str_b, (next_id,))
            except Exception:
                model_ids_invalid.append(str(model_state_id))

        return model_ids_invalid



    def duplicate_model_state(self,
                              project: str,
                              modelStateID: Union[UUID, str],
                              skipIfLatest: bool=True) -> str:
        '''
            Receives a model state ID and creates a copy of it in this project.
            This copy receives the current date, which makes it the most recent
            model state.
            If "skipIfLatest" is True and the model state with "modelStateID" is
            already the most recent state, no duplication is being performed.
            Returns the ID of the newly duplicated model state.
        '''

        if not isinstance(modelStateID, UUID):
            modelStateID = UUID(modelStateID)

        # check if model ID exists and get AI model library
        new_model_details = self.db_connector.execute(
            sql.SQL('''
                SELECT model_library
                FROM {id_cnnstate}
                WHERE id = %s
                AND partial = FALSE;
            ''').format(
                id_cnnstate=sql.Identifier(project, 'cnnstate')
            ),
            (modelStateID,),
            1
        )
        if new_model_details is None or len(new_model_details) == 0:
            raise Exception(f'Model state with ID "{modelStateID}" does not exist in project.')

        new_model_library = new_model_details[0]['model_library']

        # check if latest (if required)
        if skipIfLatest:
            is_latest = self.db_connector.execute(
                sql.SQL('''
                    SELECT id
                    FROM {id_cnnstate}
                    WHERE timeCreated = (
                        SELECT MAX(timeCreated)
                        FROM {id_cnnstate}
                    );
                ''').format(
                    id_cnnstate=sql.Identifier(project, 'cnnstate')
                ),
                None,
                1
            )
            if is_latest is not None and len(is_latest) and is_latest[0]['id'] == modelStateID:
                # is already latest
                return str(modelStateID)

        # get current AI model and settings
        current_model_details = self.db_connector.execute('''
            SELECT ai_model_library, ai_model_settings
            FROM aide_admin.project
            WHERE shortname = %s;
        ''', (project,), 1)

        if current_model_details is not None and len(current_model_details) > 0:
            current_model_details = current_model_details[0]

        insertion_args = []

        if current_model_details['ai_model_library'] != new_model_library:
            # user wants to switch to another AI model; update settings accordingly
            ai_model_update_str = sql.SQL('''
                UPDATE aide_admin.project
                SET ai_model_library = %s,
                ai_model_settings = NULL
                WHERE shortname = %s;
            ''')
            insertion_args.extend([new_model_library, project])
        else:
            # same AI model
            ai_model_update_str = sql.SQL('')

        insertion_args.append(modelStateID)

        # perform the actual duplication
        new_model_state_id = self.db_connector.execute(
            sql.SQL('''
                {aiModelUpdateStr};
                INSERT INTO {id_cnnstate} (model_library, alCriterion_library, timeCreated,
                stateDict, stats, partial, marketplace_origin_id, imported_from_marketplace)
                SELECT model_library, alCriterion_library, NOW(),
                    stateDict, stats, FALSE, NULL, imported_from_marketplace
                    FROM {id_cnnstate}
                    WHERE id = %s
                RETURNING id;
            ''').format(
                aiModelUpdateStr=ai_model_update_str,
                id_cnnstate=sql.Identifier(project, 'cnnstate')
            ),
            tuple(insertion_args),
            1
        )
        if new_model_state_id is None or len(new_model_state_id) == 0:
            raise Exception('An unknown error occurred trying to duplicate model state ' + \
                            f'with id "{modelStateID}".')

        new_model_state_id = new_model_state_id[0]['id']

        return str(new_model_state_id)



    def get_model_training_statistics(self,
                                      project: str,
                                      modelStateIDs: Iterable[Union[UUID, str]]=None,
                                      modelLibraries: Iterable[str]=None,
                                      skipImportedModels: bool=True) -> dict:
        '''
            Assembles statistics as returned by the model (if done so). Returned
            statistics may be dicts with keys for variable names and values for
            each model state. None is appended for each model state and variable
            that does not exist.
            The optional input "modelStateIDs" may be a str, UUID, or list of str
            or UUID, and indicates a filter for model state IDs to be included
            in the assembly.
            Optional input "modelLibraries" may be a str or list of str and filters
            model libraries that were used in the project over time.
            If "skipImportedModels" is True, model states that were directly imported
            from the Model Marketplace are ignored. This is True by default, since these
            model states usually don't contain statistics, let alone values that are re-
            lated to the current project.
        '''
        # verify IDs
        if modelStateIDs is not None:
            if not isinstance(modelStateIDs, Iterable):
                modelStateIDs = [modelStateIDs]
            uuids = []
            for m in modelStateIDs:
                try:
                    uuids.append((UUID(m),))
                except Exception:
                    pass
            modelStateIDs = uuids
            if len(modelStateIDs) == 0:
                modelStateIDs = None

        sql_filter = ''
        query_args = []

        # verify libraries
        if modelLibraries is not None:
            if not isinstance(modelLibraries, Iterable):
                modelLibraries = [modelLibraries]
            if len(modelLibraries):
                modelLibraries = tuple([(str(m_lib),) for m_lib in modelLibraries])
                query_args.append((modelLibraries,))
                sql_filter = 'WHERE model_library IN %s'

        # get all statistics
        if modelStateIDs is not None and len(modelStateIDs):
            if len(sql_filter) > 0:
                sql_filter += ' AND id IN %s'
            else:
                sql_filter = 'WHERE id IN %s'
            query_args.append((tuple([(m,) for m in modelStateIDs]),))

        # skip imported model states
        if skipImportedModels:
            if len(sql_filter) > 0:
                sql_filter += ' AND imported_from_marketplace IS FALSE'
            else:
                sql_filter = 'WHERE imported_from_marketplace IS FALSE'

        #TODO: add number of images used to train model, too?
        query_result = self.db_connector.execute(sql.SQL('''
            SELECT id, model_library, EXTRACT(epoch FROM timeCreated) AS timeCreated, stats FROM {id_cnnstate}
            {sql_filter}
            ORDER BY timeCreated ASC;
        ''').format(
            id_cnnstate=sql.Identifier(project, 'cnnstate'),
            sql_filter=sql.SQL(sql_filter)
        ), (query_args if len(query_args) > 0 else None), 'all')

        # assemble output stats
        if query_result is None or len(query_result) == 0:
            return {}

        # separate outputs for each model library used
        model_libs = set(q['model_library'] for q in query_result)
        ids, dates, stats_raw = dict((m, []) for m in model_libs), \
                                dict((m, []) for m in model_libs), \
                                dict((m, []) for m in model_libs)
        keys = dict((m, set()) for m in model_libs)

        for q in query_result:
            model_lib = q['model_library']
            ids[model_lib].append(str(q['id']))
            dates[model_lib].append(q['timecreated'])
            try:
                q_dict = json.loads(q['stats'])
                stats_raw[model_lib].append(q_dict)
                keys[model_lib] = keys[model_lib].union(set(q_dict.keys()))
            except Exception:
                stats_raw[model_lib].append({})
                
        # assemble into series
        series = {}
        for m in model_libs:
            series[m] = dict((k, len(stats_raw[m])*[None]) for k in keys[m])

            for idx, stat in enumerate(stats_raw[m]):
                for key in keys[m]:
                    if key in stat:
                        series[m][key][idx] = stat[key]

        return {
            'ids': ids,
            'timestamps': dates,
            'series': series
        }
