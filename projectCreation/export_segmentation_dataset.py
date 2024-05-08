'''
    Pulls segmentation masks from the database and exports them into folders with specifiable format
    (JPEG, TIFF, etc.).

    2019-24 Benjamin Kellenberger
'''

import os
import argparse
from psycopg2 import sql
from util import drivers, helpers



if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Export segmentation map annotations from database to images.')
    parser.add_argument('--project', type=str, default='segtest',
                    help='Project shortname for which to export annotations.')
    parser.add_argument('--settings_filepath', type=str, default='config/settings.ini', const=1, nargs='?',
                    help='Manual specification of the directory of the settings.ini file; only considered if environment variable unset (default: "config/settings.ini").')
    parser.add_argument('--target_folder', type=str, default='export', const=1, nargs='?',
                    help='Export directory for the segmentation image files.')
    parser.add_argument('--file_format', type=str, default='TIFF', const=1, nargs='?',
                    help='File format for segmentation annotations (default: TIFF).')
    parser.add_argument('--export_annotations', type=bool, default=True, const=1, nargs='?',
                    help='Whether to export annotations (default: True).')
    parser.add_argument('--limit_users', type=str,
                    help='Which users (comma-separated list of usernames) to limit annotations to (default: None).')
    parser.add_argument('--exclude_users', type=str, default=None, const=1, nargs='?',
                    help='Comma-separated list of usernames whose annotations not to include (default: None).')
    #TODO: implement:
    # parser.add_argument('--export_predictions', type=bool, default=False, const=1, nargs='?',
    #                 help='Whether to export predictions (default: False).')
    # parser.add_argument('--predictions_min_date', type=str, default=None, const=1, nargs='?',
    #                 help='Timestamp of earliest predictions to consider (default: None, i.e. all).')
    args = parser.parse_args()

    
    # setup
    print('Setup...')
    if not 'AIDE_CONFIG_PATH' in os.environ:
        os.environ['AIDE_CONFIG_PATH'] = str(args.settings_filepath)
    
    import numpy as np
    from PIL import Image
    import base64
    from util.configDef import Config
    from modules import Database

    drivers.init_drivers(False)

    config = Config()

    # setup DB connection
    dbConn = Database(config)
    if not dbConn.canConnect():
        raise Exception('Error connecting to database.')

    # check if valid file format provided
    fileFormat = args.file_format.lower().strip()
    if not fileFormat.startswith('.'):
        fileFormat = '.' + fileFormat

    valid_file_formats = list(drivers.VALID_IMAGE_EXTENSIONS)
    valid_file_formats.extend(['.tif', '.tiff'])
    if fileFormat not in valid_file_formats:
        raise Exception('Error: provided file format ("{}") is not valid.'.format(args.file_format))

    # check if correct type of annotations
    annotationType = dbConn.execute('SELECT annotationtype FROM aide_admin.project WHERE shortname = %s;',
                            (args.project,), 1)
    if not len(annotationType):
        raise Exception(f'Project with name "{args.project}" could not be found in database.')
    annotationType = annotationType[0]['annotationtype']
    exportAnnotations = args.export_annotations
    if exportAnnotations and not (annotationType == 'segmentationMasks'):
        print('Warning: project annotations are not segmentation masks; skipping annotation export...')
        exportAnnotations = False

    os.makedirs(args.target_folder, exist_ok=True)


    # query and export label definition
    labelQuery = dbConn.execute(sql.SQL('SELECT * FROM {id_lc};').format(id_lc=sql.Identifier(args.project, 'labelclass')), None, 'all')
    with open(os.path.join(args.target_folder, 'classDefinitions.txt'), 'w') as f:
        f.write('labelclass,index\n')
        for labelIdx, l in enumerate(labelQuery):
            f.write('{},{}\n'.format(l['name'],labelIdx))


    # start querying and exporting
    if exportAnnotations:
        queryArgs = []

        # included and excluded users
        if args.limit_users is not None:
            limitUsers = []
            for u in args.limit_users.split(','):
                limitUsers.append(u.strip())
            sql_limitUsers = sql.SQL('WHERE anno.username IN %s')
            queryArgs = []
            queryArgs.append(tuple(limitUsers))
        else:
            sql_limitUsers = sql.SQL('')

        if args.exclude_users is not None:
            excludeUsers = []
            for u in args.exclude_users.split(','):
                excludeUsers.append(u.strip())
            if args.limit_users is not None:
                sql_excludeUsers = sql.SQL('AND anno.username NOT in %s')
            else:
                sql_excludeUsers = sql.SQL('WHERE anno.username IN %s')
            queryArgs.append(tuple(excludeUsers))
        else:
            sql_excludeUsers = sql.SQL('')

        if len(queryArgs) == 0:
            queryArgs = None

        queryStr = sql.SQL('''
            SELECT * FROM {id_anno} AS anno
            JOIN (SELECT id AS imID, filename FROM {id_img}) AS img
            ON anno.image = img.imID
            {sql_limitUsers}
            {sql_excludeUsers}
        ''').format(
            id_anno=sql.Identifier(args.project, 'annotation'),
            id_img=sql.Identifier(args.project, 'image'),
            sql_limitUsers=sql_limitUsers,
            sql_excludeUsers=sql_excludeUsers
        )

        allData = dbConn.execute(queryStr, queryArgs, 'all')

        # iterate
        if allData is not None and len(allData):
            print('Exporting images...\n')
            for nextItem in allData:
                # parse
                imgName = nextItem['filename']
                imgName, _ = os.path.splitext(imgName)
                targetName = os.path.join(args.target_folder, imgName+fileFormat)
                parent,_ = os.path.split(targetName)
                os.makedirs(parent, exist_ok=True)

                # convert base64 mask to image
                width = int(nextItem['width'])
                height = int(nextItem['height'])
                img = helpers.base64_to_image(nextItem['segmentationmask'],
                                              width,
                                              height,
                                              True,
                                              True,
                                              'nearest')
                # raster = np.frombuffer(base64.b64decode(nextItem['segmentationmask']), dtype=np.uint8)
                # raster = np.reshape(raster, (height,width,))
                # img = Image.fromarray(raster)
                img.save(targetName)
                print(targetName)
        else:
            print('No images to export.')
