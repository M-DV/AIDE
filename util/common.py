'''
    Common routines across modules.

    2024 Benjamin Kellenberger
'''

from typing import Union, Tuple
from uuid import UUID
from psycopg2 import sql
import numpy as np
from PIL import Image

from modules.Database.app import Database



def check_demo_mode(project: str,
                    db_connector: Database):
    '''
        Returns a bool indicating whether the project is in demo mode. Returns None if the
        project does not exist.
    '''
    try:
        response = db_connector.execute('''
            SELECT demoMode FROM aide_admin.project
            WHERE shortname = %s;''',
            (project,),
            1)
        if len(response) > 0:
            return response[0]['demomode']
        return None
    except Exception:
        return None



def get_project_immutables(project: str,
                           db_connector: Database) -> Tuple[str, str]:
    '''
        Returns the two main immutable properties of a project (i.e., annotation type and prediction
        type).

        Args:
            - "project":        str, project shortname
            - "db_connector":   Database, database connection module instance

        Returns:
            - tuple, str for immutables "annotationType" and "predictionType"
    '''
    #TODO: maybe integrate into Database and create cache
    proj_immutables = db_connector.execute(
        '''
            SELECT annotationtype, predictiontype
            FROM aide_admin.project
            WHERE shortname = %s;
        ''',
        (project,),
        1
    )
    if proj_immutables is None or len(proj_immutables) == 0:
        return None, None
    proj_immutables = proj_immutables[0]
    return proj_immutables['annotationtype'], proj_immutables['predictiontype']



def set_image_corrupt(db_connector: Database,
                      project: str,
                      image_id: UUID,
                      corrupt: bool) -> None:
    '''
        Sets the "corrupt" flag to the provided value for a given project and image ID.
    '''
    query_str = sql.SQL('''
            UPDATE {id_img}
            SET corrupt = %s
            WHERE id = %s;
        ''').format(
            id_img=sql.Identifier(project, 'image')
        )
    db_connector.execute(query_str, (corrupt,image_id,), None)



def get_pil_image(data: Union[str,np.ndarray],
                  image_id: UUID,
                  project: str,
                  db_connector: Database,
                  convert_rgb: bool=False) -> Image:
    '''
        Reads an input (file path or BytesIO object) and returns a PIL image instance. Also checks
        if the image is intact. If it is not, the "corrupt" flag is set in the database as True, and
        None is returned.
    '''
    img = None
    try:
        img = Image.open(data)
        if convert_rgb:
            # conversion implicitly verifies the image (TODO)
            img = img.convert('RGB')
        else:
            img.verify()
            img = Image.open(data)

    except Exception:
        # something failed; set "corrupt" flag to False for image
        set_image_corrupt(db_connector, project, image_id, True)
    return img
