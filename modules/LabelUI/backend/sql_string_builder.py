'''
    Functions to format SQL strings for annotation/prediction metadata querying and insertion.

    2019-24 Benjamin Kellenberger
'''

from typing import Tuple, List, Iterable, Union
import uuid
from psycopg2 import sql
from constants.dbFieldNames import FieldNames_annotation, FieldNames_prediction



def _assemble_colnames(annotation_type: str,
                       prediction_type) -> Tuple[Iterable]:

    if annotation_type is None:
        # annotation fields not needed; return prediction fields instead
        fields_pred = getattr(FieldNames_prediction, prediction_type).value
        fields_pred = [sql.Identifier(f) for f in fields_pred]
        return None, fields_pred, fields_pred

    if prediction_type is None:
        # prediction fields not needed; return annotation fields
        fields_anno = getattr(FieldNames_annotation, annotation_type).value
        fields_anno = [sql.Identifier(f) for f in fields_anno]
        return fields_anno, None, fields_anno

    # both needed; return so that both can be queried simultaneously
    fields_anno = getattr(FieldNames_annotation, annotation_type).value
    fields_pred = getattr(FieldNames_prediction, prediction_type).value
    fields_union = list(fields_anno.union(fields_pred))

    tokens_anno = []
    tokens_pred = []
    tokens_all = []
    for f in fields_union:
        if not f in fields_anno:
            tokens_anno.append(sql.SQL('NULL AS {}').format(sql.Identifier(f)))
        else:
            tokens_anno.append(sql.SQL('{}').format(sql.Identifier(f)))
        if not f in fields_pred:
            tokens_pred.append(sql.SQL('NULL AS {}').format(sql.Identifier(f)))
        else:
            tokens_pred.append(sql.SQL('{}').format(sql.Identifier(f)))
        tokens_all.append(sql.Identifier(f))

    return tokens_anno, tokens_pred, tokens_all



def get_colnames(annotation_type: str,
                 prediction_type,
                 query_type: str) -> List[str]:
    '''
        Returns a list of column names, depending on the type provided.
    '''
    if query_type == 'prediction':
        base_names = list(getattr(FieldNames_prediction, prediction_type).value)
    elif query_type == 'annotation':
        base_names = list(getattr(FieldNames_annotation, annotation_type).value)
    else:
        raise ValueError(f'{query_type} is not a recognized type.')

    base_names += ['id', 'viewcount']
    return base_names



def get_fixed_images_query_str(project: str,
                               annotation_type: str,
                               prediction_type: str,
                               demo_mode: bool=False) -> sql.SQL:
    '''
        Assembles an SQL string to get metadata for a fixed set of images.
    '''
    fields_anno, fields_pred, fields_union = _assemble_colnames(annotation_type, prediction_type)

    username_str_iu = 'WHERE username = %s'
    username_str = username_str_iu + ' OR shared = TRUE'
    if demo_mode:
        username_str, username_str_iu = '', ''

    query_str = sql.SQL('''
        SELECT id, image, cType, viewcount, EXTRACT(epoch FROM last_checked) as last_checked,
            filename, w_x, w_y, w_width, w_height, isGoldenQuestion,
        COALESCE(bookmark, false) AS isBookmarked, {allCols} FROM (
            SELECT id AS image, filename,
                x AS w_x, y AS w_y, width AS w_width, height AS w_height,
                isGoldenQuestion
            FROM {id_img}
            WHERE id IN %s
        ) AS img
        LEFT OUTER JOIN (
            SELECT id, image AS imID, 'annotation' AS cType, {annoCols} FROM {id_anno} AS anno
            {usernameString}
            UNION ALL
            SELECT id, image AS imID, 'prediction' AS cType, {predCols} FROM {id_pred} AS pred
            WHERE cnnstate IN (
                SELECT id FROM {id_cnnstate}
            )
        ) AS contents ON img.image = contents.imID
        LEFT OUTER JOIN (SELECT image AS iu_image, viewcount, last_checked, username FROM {id_iu}
        {usernameString_iu}) AS iu ON img.image = iu.iu_image
        LEFT OUTER JOIN (
            SELECT image AS bmImg, true AS bookmark
            FROM {id_bookmark}
        ) AS bm ON img.image = bm.bmImg;
    ''').format(
        id_img=sql.Identifier(project, 'image'),
        id_anno=sql.Identifier(project, 'annotation'),
        id_pred=sql.Identifier(project, 'prediction'),
        id_cnnstate=sql.Identifier(project, 'cnnstate'),
        id_iu=sql.Identifier(project, 'image_user'),
        id_bookmark=sql.Identifier(project, 'bookmark'),
        allCols=sql.SQL(', ').join(fields_union),
        annoCols=sql.SQL(', ').join(fields_anno),
        predCols=sql.SQL(', ').join(fields_pred),
        usernameString=sql.SQL(username_str),
        usernameString_iu=sql.SQL(username_str_iu)
    )

    return query_str



def get_next_batch_query_str(project: str,
                             annotation_type: str,
                             prediction_type: str,
                             order: str='unlabeled',
                             subset: str='default',
                             demo_mode: bool=False) -> sql.SQL:
    '''
        Assembles a DB query string according to the AL and viewcount ranking criterion.
        Inputs:
        - order: specifies sorting criterion for request:
            - 'unlabeled': prioritize images that have not (yet) been viewed
                by the current user (i.e., last_requested timestamp is None or older than 15 minutes
                (TODO: make project-specific parameter?))
            - 'labeled': put images first in order that have a high user viewcount
        - subset: hard constraint on the label status of the images:
            - 'default': do not constrain query set
            - 'forceLabeled': images must have a viewcount of 1 or more
            - 'forceUnlabeled': images must not have been viewed by the current user
        - demoMode: set to True to disable sorting criterion and return images in random
                    order instead.
        
        Note: images market with "isGoldenQuestion" = True will be prioritized if their view-
                count by the current user is 0.
    '''

    # column names
    fields_anno, fields_pred, fields_union = _assemble_colnames(annotation_type, prediction_type)

    # subset selection fragment
    subset_fragment_a = 'WHERE isGoldenQuestion = FALSE'
    subset_fragment_b = ''
    order_spec_a = ''
    order_spec_b = ''
    if subset == 'forceLabeled':
        subset_fragment_a = 'WHERE viewcount > 0 AND isGoldenQuestion = FALSE'
        subset_fragment_b = 'WHERE viewcount > 0'
    elif subset == 'forceUnlabeled':
        subset_fragment_a = 'WHERE (viewcount IS NULL OR viewcount = 0) ' + \
                                'AND isGoldenQuestion = FALSE'
        subset_fragment_b = 'WHERE (viewcount IS NULL OR viewcount = 0)'

    if len(subset_fragment_a) > 0:
        subset_fragment_a += ' AND (NOW() - COALESCE(img.last_requested, to_timestamp(0))) > ' + \
                                'interval \'900 second\''
    else:
        subset_fragment_a = 'WHERE (NOW() - COALESCE(img.last_requested, to_timestamp(0))) > ' + \
                                'interval \'900 second\''

    if order == 'unlabeled':
        order_spec_a = 'ORDER BY isgoldenquestion DESC NULLS LAST, viewcount ASC NULLS FIRST, ' + \
                            'annoCount ASC NULLS FIRST, score DESC NULLS LAST'
        order_spec_b = 'ORDER BY isgoldenquestion DESC NULLS LAST, viewcount ASC NULLS FIRST, ' + \
                            'annoCount ASC NULLS FIRST, score DESC NULLS LAST'
    elif order == 'labeled':
        order_spec_a = 'ORDER BY viewcount DESC NULLS LAST, isgoldenquestion DESC NULLS LAST, ' + \
                            'score DESC NULLS LAST'
        order_spec_b = 'ORDER BY viewcount DESC NULLS LAST, isgoldenquestion DESC NULLS LAST, ' + \
                            'score DESC NULLS LAST'
    elif order == 'random':
        order_spec_a = 'ORDER BY last_checked ASC, RANDOM()'
        order_spec_b = 'ORDER BY RANDOM()'
    order_spec_a += ', timeCreated DESC'
    order_spec_b += ', timeCreated DESC'

    username_str = 'WHERE username = %s OR shared = TRUE'
    if demo_mode:
        username_str = ''
        order_spec_a = 'ORDER BY last_checked ASC, RANDOM()'
        order_spec_b = 'ORDER BY RANDOM()'
        gq_user = sql.SQL('')
    else:
        gq_user = sql.SQL('''AND id NOT IN (
            SELECT image FROM {id_iu}
            WHERE username = %s
        )''').format(
            id_iu=sql.Identifier(project, 'image_user')
        )

    query_str = sql.SQL('''
        SELECT id, image, cType, viewcount, EXTRACT(epoch FROM last_checked) as last_checked,
            filename, w_x, w_y, w_width, w_height, isGoldenQuestion,
        COALESCE(bookmark, false) AS isBookmarked, {allCols} FROM (
        SELECT * FROM (
            SELECT id AS image, filename,
                x AS w_x, y AS w_y, width AS w_width, height AS w_height, 0 AS viewcount,
                0 AS annoCount, NULL AS last_checked, 1E9 AS score, NULL AS timeCreated,
                isGoldenQuestion
            FROM {id_img} AS img
            WHERE isGoldenQuestion = TRUE
            {gq_user}
            UNION ALL
            SELECT id AS image, filename,
                x AS w_x, y AS w_y, width AS w_width, height AS w_height,
                viewcount, annoCount, last_checked, score, timeCreated,
                isGoldenQuestion FROM {id_img} AS img
            LEFT OUTER JOIN (
                SELECT * FROM {id_iu}
            ) AS iu ON img.id = iu.image
            LEFT OUTER JOIN (
                SELECT image, SUM(confidence)/COUNT(confidence) AS score, timeCreated
                FROM {id_pred}
                WHERE cnnstate IN (
                    SELECT id FROM {id_cnnstate}
                )
                GROUP BY image, timeCreated
            ) AS img_score ON img.id = img_score.image
            LEFT OUTER JOIN (
                SELECT image, COUNT(*) AS annoCount
                FROM {id_anno}
                {usernameString}
                GROUP BY image
            ) AS anno_score ON img.id = anno_score.image
            {subset}
        ) AS imgQ
        {order_a}
        LIMIT %s
        ) AS img_query
        LEFT OUTER JOIN (
            SELECT id, image AS imID, 'annotation' AS cType, {annoCols} FROM {id_anno} AS anno
            {usernameString}
            UNION ALL
            SELECT id, image AS imID, 'prediction' AS cType, {predCols} FROM {id_pred} AS pred
            WHERE cnnstate IN (
                SELECT id FROM {id_cnnstate}
            )
        ) AS contents ON img_query.image = contents.imID
        LEFT OUTER JOIN (
            SELECT image AS bmImg, true AS bookmark
            FROM {id_bookmark}
        ) AS bm ON img_query.image = bm.bmImg
        {subset_b}
        {order_b};
    ''').format(
        id_img=sql.Identifier(project, 'image'),
        id_anno=sql.Identifier(project, 'annotation'),
        id_pred=sql.Identifier(project, 'prediction'),
        id_iu=sql.Identifier(project, 'image_user'),
        id_cnnstate=sql.Identifier(project, 'cnnstate'),
        id_bookmark=sql.Identifier(project, 'bookmark'),
        gq_user=gq_user,
        allCols=sql.SQL(', ').join(fields_union),
        annoCols=sql.SQL(', ').join(fields_anno),
        predCols=sql.SQL(', ').join(fields_pred),
        subset=sql.SQL(subset_fragment_a),
        subset_b=sql.SQL(subset_fragment_b),
        order_a=sql.SQL(order_spec_a),
        order_b=sql.SQL(order_spec_b),
        usernameString=sql.SQL(username_str)
    )

    return query_str



def get_next_tile_cardinal_direction_query_str(project: str) -> sql.SQL:
    '''
        Assembles string to query next image tiles in all four cardinal direction, based on current
        one.
    '''
    return sql.SQL('''
        WITH currImg AS (
            SELECT x, y, filename
            FROM {id_image}
            WHERE id = %s
        ),
        imgPool AS (
            SELECT id, x, y
            FROM {id_image}
            WHERE filename = (SELECT filename FROM currImg)
        )
        SELECT * FROM (
            SELECT id, x, y, 'w' AS cd
            FROM imgPool
            WHERE x < (SELECT x FROM currImg)
            AND y = (SELECT y FROM currImg)
            ORDER BY x DESC
            LIMIT 1
        ) AS west
        UNION ALL
        SELECT * FROM (
            SELECT id, x, y, 'e' AS cd
            FROM imgPool
            WHERE x > (SELECT x FROM currImg)
            AND y = (SELECT y FROM currImg)
            ORDER BY x ASC
            LIMIT 1
        ) AS east
        UNION ALL
        SELECT * FROM (
            SELECT id, x, y, 's' AS cd
            FROM imgPool
            WHERE y > (SELECT y FROM currImg)
            AND x = (SELECT x FROM currImg)
            ORDER BY y ASC
            LIMIT 1
        ) AS south
        UNION ALL
        SELECT * FROM (
            SELECT id, x, y, 'n' AS cd
            FROM imgPool
            WHERE y < (SELECT y FROM currImg)
            AND x = (SELECT x FROM currImg)
            ORDER BY y DESC
            LIMIT 1
        ) AS north
    ''').format(
        id_image=sql.Identifier(project, 'image')
    )



def get_sample_data_query_str(project: str,
                              annotation_type: str,
                              prediction_type: str) -> sql.SQL:
    '''
        Returns static sample data tailored to a given project.
    '''
    fields_anno, fields_pred, fields_union = _assemble_colnames(annotation_type, prediction_type)

    query_str = sql.SQL('''
        SELECT id, image, cType, 1 AS viewcount, NULL AS last_checked, NULL AS username, filename,
            w_x, w_y, w_width, w_height, isGoldenQuestion,
        COALESCE(bookmark, false) AS isBookmarked, {allCols} FROM (
            SELECT id AS image, filename,
                x AS w_x, y AS w_y, width AS w_width, height AS w_height, isGoldenQuestion
            FROM {id_img}
            WHERE COALESCE(corrupt,false) IS FALSE
            AND id IN (
                SELECT anno.image FROM {id_anno} AS anno
                JOIN {id_pred} AS pred
                ON anno.image = pred.image
            )
            ORDER BY isGoldenQuestion DESC NULLS LAST
            LIMIT 1
        ) AS img
        JOIN (
            SELECT id, image AS imID, 'annotation' AS cType, {annoCols} FROM {id_anno}
            UNION ALL
            SELECT id, image AS imID, 'prediction' AS cType, {predCols} FROM {id_pred}
        ) AS meta
        ON img.image = meta.imID
        LEFT OUTER JOIN (
            SELECT image AS bmImg, true AS bookmark
            FROM {id_bookmark}
        ) AS bm ON img.image = bm.bmImg;
    ''').format(
        id_img=sql.Identifier(project, 'image'),
        id_anno=sql.Identifier(project, 'annotation'),
        id_pred=sql.Identifier(project, 'prediction'),
        id_bookmark=sql.Identifier(project, 'bookmark'),
        allCols=sql.SQL(', ').join(fields_union),
        annoCols=sql.SQL(', ').join(fields_anno),
        predCols=sql.SQL(', ').join(fields_pred)
    )

    return query_str



def get_date_query_str(project: str,
                       annotation_type: str,
                       min_age: float,
                       max_age: float,
                       user_names: Union[Iterable[str],str],
                       skip_empty_images: bool,
                       golden_questions_only: bool,
                       last_image_uuid: uuid.UUID=None) -> sql.SQL:
    '''
        Assembles a DB query string that returns images between a time range. Useful for reviewing
        existing annotations.
        
        Inputs:
            - minAge: earliest timestamp on which the image(s) have been viewed.
                        Set to None to leave unrestricted.
            - maxAge: latest timestamp of viewing (None = unrestricted).
            - userNames: user names to filter the images to. If string, only images
                            viewed by this respective user are returned. If list, the images are
                            filtered according to any of the names within. If None, no user
                            restriction is placed.
            - skipEmptyImages: if True, images without an annotation will be ignored.
            - goldenQuestionsOnly: if True, images without flag isGoldenQuestion =
                                    True will be ignored.
            - lastImageUUID: if UUID, only images after this one in alphabetical order
                                will be queried. Useful to review images that have been
                                batch-imported and hence have identical timestamps added.
    '''

    # column names
    fields_anno, _, _ = _assemble_colnames(annotation_type, None)

    # user names
    username_str = ''
    if user_names is not None:
        if isinstance(user_names, str):
            username_str = 'WHERE username = %s'
        elif isinstance(user_names, Iterable):
            username_str = 'WHERE username IN %s'
        else:
            raise ValueError('Invalid property for user names')

    # date range
    timestamp_str = None
    if min_age is not None:
        prefix = ('WHERE' if username_str == '' else 'AND')
        timestamp_str = f'{prefix} last_checked::TIMESTAMP >= TO_TIMESTAMP(%s)'
    if max_age is not None:
        prefix = ('WHERE' if (username_str == '' and timestamp_str == '') else 'AND')
        timestamp_str += f' {prefix} last_checked::TIMESTAMP <= TO_TIMESTAMP(%s)'

    # min image UUID
    last_uuid_str = ''
    if isinstance(last_image_uuid, uuid.UUID):
        last_uuid_str = 'AND image > %s'

    # empty images
    if skip_empty_images:
        skip_empty_str = sql.SQL('''
        AND image IN (
            SELECT image FROM {id_anno}
            {usernameString}
        )
        ''').format(id_anno=sql.Identifier(project, 'annotation'),
            usernameString=sql.SQL(username_str))
    else:
        skip_empty_str = sql.SQL('')

    # golden questions
    if golden_questions_only:
        golden_questions_str = sql.SQL('WHERE isGoldenQuestion = TRUE')
    else:
        golden_questions_str = sql.SQL('')

    query_str = sql.SQL('''
        SELECT id, image, cType, username, viewcount,
            EXTRACT(epoch FROM last_checked) as last_checked, filename,
            w_x, w_y, w_width, w_height, isGoldenQuestion,
        COALESCE(bookmark, false) AS isBookmarked, {annoCols} FROM (
            SELECT id AS image, filename,
                x AS w_x, y AS w_y, width AS w_width, height AS w_height, isGoldenQuestion
            FROM {id_image}
            {goldenQuestionsString}
        ) AS img
        JOIN (SELECT image AS iu_image, viewcount, last_checked, username FROM {id_iu}
        {usernameString}
        {timestampString}
        {lastUUIDstring}
        {skipEmptyString}
        ORDER BY last_checked ASC, image ASC
        LIMIT %s) AS iu ON img.image = iu.iu_image
        LEFT OUTER JOIN (
            SELECT id, image AS imID, 'annotation' AS cType, {annoCols} FROM {id_anno} AS anno
            {usernameString}
        ) AS contents ON img.image = contents.imID
        LEFT OUTER JOIN (
            SELECT image AS bmImg, true AS bookmark
            FROM {id_bookmark}
        ) AS bm ON img.image = bm.bmImg;
    ''').format(
        annoCols=sql.SQL(', ').join(fields_anno),
        id_image=sql.Identifier(project, 'image'),
        id_iu=sql.Identifier(project, 'image_user'),
        id_anno=sql.Identifier(project, 'annotation'),
        id_bookmark=sql.Identifier(project, 'bookmark'),
        usernameString=sql.SQL(username_str),
        timestampString=sql.SQL(timestamp_str),
        lastUUIDstring=sql.SQL(last_uuid_str),
        skipEmptyString=skip_empty_str,
        goldenQuestionsString=golden_questions_str
    )

    return query_str



def get_time_range_query_str(project: str,
                             user_names: Union[Iterable[str],str],
                             skip_empty_images: bool,
                             golden_questions_only: bool) -> sql.SQL:
    '''
        Assembles a DB query string that returns a minimum and maximum timestamp between which the
        image(s) have been annotated.
        Inputs:

            - userNames: user names to filter the images to. If string, only images
                            viewed by this respective user are considered. If list, the images are
                            filtered according to any of the names within. If None, no user
                            restriction is placed.
            - skipEmptyImages: if True, images without an annotation will be ignored.
            - goldenQuestionsOnly: if True, images without flag isGoldenQuestion =
                                    True will be ignored.
    '''

    # params
    username_str = ''
    if user_names is not None:
        if isinstance(user_names, str):
            username_str = 'WHERE iu.username = %s'
        elif isinstance(user_names, Iterable):
            username_str = 'WHERE iu.username IN %s'
        else:
            raise ValueError('Invalid property for user names')

    if skip_empty_images:
        skip_empty_str = sql.SQL('''
        JOIN {id_anno} AS anno ON iu.image = anno.image
        ''').format(id_anno=sql.Identifier(project, 'annotation'))
    else:
        skip_empty_str = sql.SQL('')

    if golden_questions_only:
        golden_questions_str = sql.SQL('''
        JOIN (
            SELECT id FROM {id_img}
            WHERE isGoldenQuestion = TRUE
        ) AS imgQ ON query.id = imgQ.id
        ''').format(
            id_img=sql.Identifier(project, 'image')
        )
    else:
        golden_questions_str = sql.SQL('')

    query_str = sql.SQL('''
        SELECT EXTRACT(epoch FROM MIN(last_checked)) AS minTimestamp,
            EXTRACT(epoch FROM MAX(last_checked)) AS maxTimestamp
        FROM (
            SELECT iu.image AS id, last_checked FROM {id_iu} AS iu
            {skipEmptyString}
            {usernameString}
        ) AS query
        {goldenQuestionsString};
    ''').format(
        id_iu=sql.Identifier(project, 'image_user'),
        usernameString=sql.SQL(username_str),
        skipEmptyString=skip_empty_str,
        goldenQuestionsString=golden_questions_str)

    return query_str
