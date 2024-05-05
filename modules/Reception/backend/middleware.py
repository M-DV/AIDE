'''
    Handles data flow about projects in general.

    2019-24 Benjamin Kellenberger
'''

from typing import List
from psycopg2 import sql

from util.helpers import current_time



class ReceptionMiddleware:
    '''
        Reception middleware, responsible for queries about projects as a whole.
    '''

    def __init__(self, config, dbConnector):
        self.config = config
        self.db_connector = dbConnector


    def get_project_info(self,
                         username: str=None,
                         is_super_user: bool=False,
                         archived: bool=None) -> dict:
        '''
            Returns metadata about projects:
            - names
            - whether the projects are archived or not
            - links to interface (if user is authenticated)
            - requests for authentication (else)    TODO
            - links to stats and review page (if admin) TODO
            - etc.
        '''
        assert archived is None or isinstance(archived, bool)
        now = current_time()

        if is_super_user:
            auth_str = ''
            query_vals = None
        elif username is not None:
            auth_str = 'WHERE (username = %s OR demoMode = TRUE OR isPublic = TRUE)'
            query_vals = (username,)
        else:
            auth_str = 'WHERE (demoMode = TRUE OR isPublic = TRUE)'
            query_vals = None
        if isinstance(archived, bool):
            if len(auth_str) > 0:
                archived_str = f' AND archived = {archived}'
            else:
                archived_str = f'WHERE archived = {archived}'
        else:
            archived_str = ''

        query_str = sql.SQL('''SELECT shortname, name, description, archived,
            username, isAdmin,
            admitted_until, blocked_until,
            annotationType, predictionType, isPublic, demoMode, interface_enabled, archived, ai_model_enabled,
            ai_model_library,
            CASE WHEN username = owner THEN TRUE ELSE FALSE END AS is_owner
            FROM aide_admin.project AS proj
            FULL OUTER JOIN (SELECT * FROM aide_admin.authentication
            ) AS auth ON proj.shortname = auth.project
            {authStr}
            {archived_str};
        ''').format(authStr=sql.SQL(auth_str),
            archived_str=sql.SQL(archived_str))

        result = self.db_connector.execute(query_str,
                                           query_vals,
                                           'all')
        response = {}
        if result is not None and len(result):
            for res in result:
                proj_shortname = res['shortname']
                if proj_shortname not in response:
                    user_admitted = True
                    if res['admitted_until'] is not None and res['admitted_until'] < now:
                        user_admitted = False
                    if res['blocked_until'] is not None and res['blocked_until'] >= now:
                        user_admitted = False
                    response[proj_shortname] = {
                        'name': res['name'],
                        'description': res['description'],
                        'archived': res['archived'],
                        'isOwner': res['is_owner'],
                        'annotationType': res['annotationtype'],
                        'predictionType': res['predictiontype'],
                        'isPublic': res['ispublic'],
                        'demoMode': res['demomode'],
                        'interface_enabled': res['interface_enabled'] and not res['archived'],
                        'aiModelEnabled': res['ai_model_enabled'],
                        'aiModelSelected': isinstance(res['ai_model_library'], str) and \
                                            len(res['ai_model_library'])>0,
                        'userAdmitted': user_admitted
                    }
                if is_super_user:
                    response[proj_shortname]['role'] = 'super user'
                elif username is not None and res['username'] == username:
                    if res['isadmin']:
                        response[proj_shortname]['role'] = 'admin'
                    else:
                        response[proj_shortname]['role'] = 'member'

        return response


    def enroll_in_project(self,
                          project: str,
                          username: str,
                          secret_token: str=None) -> bool:
        '''
            Adds the user to the project if it allows arbitrary users to join. Returns True if this
            succeeded, else False.
        '''
        try:
            # check if project is public, and whether user is already member of it
            query_str = sql.SQL('''SELECT isPublic, secret_token
            FROM aide_admin.project
            WHERE shortname = %s;
            ''')
            result = self.db_connector.execute(query_str,
                                               (project,),
                                               1)

            # only allow enrolment if project is public, or else if secret tokens match
            if len(result) == 0:
                return False
            if not result[0]['ispublic']:
                # check if secret tokens match
                if secret_token is None or secret_token != result[0]['secret_token']:
                    return False

            # add user
            query_str = '''INSERT INTO aide_admin.authentication (username, project, isAdmin)
            VALUES (%s, %s, FALSE)
            ON CONFLICT (username, project) DO NOTHING;
            '''
            self.db_connector.execute(query_str,
                                      (username,project,),
                                      None)
            return True
        except Exception as exc:
            print(exc)
            return False


    def get_sample_images(self,
                          project: str,
                          limit: int=128) -> List[str]:
        '''
            Returns sample image URLs from the specified project for backdrop
            visualization on the landing page.
            Images are sorted descending according to the following criteria,
            in a row:
            1. last_requested
            2. date_added
            3. number of annotations
            4. number of predictions
            5. random
        '''
        query_str = sql.SQL('''
            SELECT filename FROM {id_img} AS img
            LEFT OUTER JOIN (
                SELECT img_anno AS img_id, cnt_anno, cnt_pred FROM (
                    SELECT image AS img_anno, COUNT(image) AS cnt_anno
                    FROM {id_anno}
                    GROUP BY img_anno
                ) AS anno
                FULL OUTER JOIN (
                    SELECT image AS img_pred, COUNT(image) AS cnt_pred
                    FROM {id_pred}
                    GROUP BY img_pred
                ) AS pred
                ON anno.img_anno = pred.img_pred
            ) AS metaQuery
            ON img.id = metaQuery.img_id
            ORDER BY last_requested DESC NULLS LAST, date_added DESC NULLS LAST,
                cnt_anno DESC NULLS LAST, cnt_pred DESC NULLS LAST, random()
            LIMIT %s;
        ''').format(
            id_img=sql.Identifier(project, 'image'),
            id_anno=sql.Identifier(project, 'annotation'),
            id_pred=sql.Identifier(project, 'prediction')
        )
        result = self.db_connector.execute(query_str, (limit,), 'all')
        response = []
        for res in result:
            response.append(res['filename'])
        return response
