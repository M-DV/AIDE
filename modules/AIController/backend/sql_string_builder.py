'''
    SQL string builder for AIController.

    2019-24 Benjamin Kellenberger
'''

from typing import Iterable, Tuple
from uuid import UUID
from psycopg2 import sql



def get_inference_query_string(project: str,
                               force_unlabeled: bool=True,
                               tags: Iterable=None,
                               golden_questions_only: bool=False,
                               limit: int=None) -> Tuple[sql.SQL, Tuple]:
    '''
        Assembles SQL string to query the latest images from a project for model inference.

        Args:
            - "project":                str, project shortname
            - "force_unlabeled:         bool, only queries images that have not yet been checked
                                        by users if True (default) to be queried (default: 0 =
                                        no limit).
            - "tags"                    iterable of str or UUID, only include images that have been
                                        assigned to at least one of the specified tags. If special
                                        keyword "tag_none" is found, only images that have not been
                                        assigned to any tag will be queried.
            - "golden_questions_only":  bool, only includes images marked as "golden question"
                                        if True (default: False).
            - "limit":                  int, maximum number of images to query (default: None =
                                        no limit).
        
        Returns:
            - SQL, SQL string object to perform query.
            - query values as tuple.
    '''
    query_vals = []

    if golden_questions_only:
        gq_str = sql.SQL('WHERE isGoldenQuestion IS TRUE')
    else:
        gq_str = sql.SQL('')

    condition_str = []
    if force_unlabeled:
        condition_str.append('''viewcount IS NULL
            AND (corrupt IS NULL OR corrupt = FALSE)''')
    else:
        condition_str.append('corrupt IS NULL OR corrupt = FALSE')

    # tags
    if tags is not None:
        if isinstance(tags, (str, UUID)):
            tags = [tags]
        if len(tags) > 0:
            if tags[0] == 'tag_none':
                # select all images without tags
                condition_str.append('''image.id NOT IN (
                        SELECT image_id
                        FROM {id_tag_image})''')
            else:
                tags = [tag if isinstance(tag, UUID) else UUID(tag) for tag in tags]
                condition_str.append('''image.id IN (
                        SELECT image_id
                        FROM {id_tag_image}
                        WHERE tag_id IN %s
                    )''')
                query_vals.append(tuple(tags))

    condition_str = sql.SQL('WHERE ' + ' AND '.join(condition_str)).format(
        id_tag_image=sql.Identifier(project, 'tag_image')
    )

    if limit is None or limit <= 0:
        limit_str = sql.SQL('')
    else:
        limit_str = sql.SQL('LIMIT %s')
        query_vals.append(limit)

    query_str = sql.SQL('''
        SELECT query.imageID AS image FROM (
            SELECT image.id AS imageID, image_user.viewcount FROM (
                SELECT * FROM {id_img}
                {gqString}
            ) AS image
            LEFT OUTER JOIN {id_iu}
            ON image.id = image_user.image
            {conditionString}
            ORDER BY image_user.viewcount ASC NULLS FIRST
            {limit}
        ) AS query;
    ''').format(
        id_img=sql.Identifier(project, 'image'),
        id_iu=sql.Identifier(project, 'image_user'),
        gqString=gq_str,
        conditionString=condition_str,
        limit=limit_str
    )
    return query_str, tuple(query_vals)


#TODO: not used anymore
# def get_latest_query_string(project: str,
#                             min_num_anno_per_image: int=0,
#                             limit: int=None) -> sql.SQL:
#     '''
#         Assembles SQL string to query the latest images from a project to be labeled.

#         Args:
#             - "project":                str, project shortname
#             - "min_num_anno_per_image:  int, minimum number of annotations per image for image
#                                         to be queried (default: 0 = no limit)
#             - "limit":                  int, maximum number of images to query (default: None =
#                                         no limit)
        
#         Returns:
#             - SQL, SQL string object to perform query.
#     '''
#     if limit is None or limit <= 0:
#         limit_str = sql.SQL('')
#     else:
#         limit_str = sql.SQL('LIMIT %s')

#     if min_num_anno_per_image <= 0:
#         # no restriction on number of annotations per image
#         query_str = sql.SQL('''
#             SELECT newestAnno.image FROM (
#                 SELECT image, last_checked FROM {id_iu} AS iu
#                 -- WHERE iu.last_checked > COALESCE(to_timestamp(0), (SELECT MAX(timecreated) FROM {id_cnnstate}))
#                 ORDER BY iu.last_checked ASC
#                 {limit}
#             ) AS newestAnno;
#         ''').format(
#             id_iu=sql.Identifier(project, 'image_user'),
#             id_cnnstate=sql.Identifier(project, 'cnnstate'),
#             limit=limit_str)
#     else:
#         query_str = sql.SQL('''
#             SELECT newestAnno.image FROM (
#                 SELECT image, last_checked FROM {id_iu} AS iu
#                 WHERE image IN (
#                     SELECT image FROM (
#                         SELECT image, COUNT(*) AS cnt
#                         FROM {schema}.annotation
#                         GROUP BY image
#                         ) AS annoCount
#                     WHERE annoCount.cnt > {minAnnoCount}
#                 )
#                 ORDER BY iu.last_checked ASC
#                 LIMIT {limit}
#             ) AS newestAnno;
#         ''').format(
#             id_iu=sql.Identifier(project, 'image_user'),
#             minAnnoCount=min_num_anno_per_image,
#             limit=limit)
#     return query_str
